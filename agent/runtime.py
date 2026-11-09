"""Run service layer: the API, the UI and (partly) the CLI drive the pipeline through this.

A run is a folder under runtime.runs_dir:

    <runs_dir>/<run_id>/run.json        metadata and lifecycle status
    <runs_dir>/<run_id>/discovery.json  the input payload
    <runs_dir>/<run_id>/events.jsonl    one event per node (or interrupt / error)
    <runs_dir>/<run_id>/artifacts/      the reporter's output (HCL, quarantine report, notes)

LangGraph checkpoints (pause / resume / re-run) live in a shared SQLite database keyed by
run id. Pause points are named so the UI does not need to know node names:

    review_cim      -> before hcl_generator (edit the CIM, then approve)
    approve_output  -> before reporter      (approve before anything is written)
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from loguru import logger
from pydantic import BaseModel

from agent import graph as graph_module
from agent.graph import NODE_ORDER
from agent.nodes.ingest import validate_discovery_payload
from cim.schema import (
    CanonicalInfrastructureModel,
    TargetProvider,
)

PAUSE_POINTS: dict[str, str] = {
    "review_cim": "hcl_generator",
    "approve_output": "reporter",
}
NODE_TO_PAUSE_POINT: dict[str, str] = {node: name for name, node in PAUSE_POINTS.items()}
TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "error", "cancelled"})

SUPPORTED_CLOUDS = ("aws", "azure", "gcp", "openstack")
GENERATION_MODES = ("deterministic", "llm", "hybrid")
LLM_PROVIDERS = ("anthropic", "openai", "google")
PROVIDER_DEFAULT_MODELS = {"anthropic": "claude-opus-5", "openai": "gpt-4o", "google": "gemini-2.0-flash"}

# State keys an operator may patch while a run is paused, and how they are validated.
PATCHABLE_KEYS: dict[str, type[BaseModel] | None] = {
    "sized_cim": CanonicalInfrastructureModel,
    "cim": CanonicalInfrastructureModel,
    "quarantine_queue": None,
}

_CHECKPOINT_TYPES = (
    ("cim.schema", "CanonicalInfrastructureModel"),
    ("cim.schema", "TargetProvider"),
    ("cim.schema", "SourcePlatform"),
    ("cim.schema", "MigrationStatus"),
    ("cim.schema", "Architecture"),
    ("cim.schema", "ClusterSemantics"),
)


class RunError(ValueError):
    """Invalid request against a run (unknown id, wrong lifecycle state, bad patch)."""


@dataclass
class RunOptions:
    cloud: str
    environment: str
    owner: str
    mode: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    skip_validation: bool = False
    skip_opa: bool = False
    no_mcp: bool = False
    dry_run: bool = False
    llm_review_notes: bool = True
    # None = use runtime.default_pause_points; [] = run straight through without pausing.
    pause_points: list[str] | None = None

    def validate(self) -> None:
        if self.cloud.lower() not in SUPPORTED_CLOUDS:
            raise RunError(f"cloud must be one of {', '.join(SUPPORTED_CLOUDS)}")
        if self.mode and self.mode.lower() not in GENERATION_MODES:
            raise RunError(f"mode must be one of {', '.join(GENERATION_MODES)}")
        if self.llm_provider and self.llm_provider.lower() not in LLM_PROVIDERS:
            raise RunError(f"llm_provider must be one of {', '.join(LLM_PROVIDERS)}")
        unknown = [name for name in (self.pause_points or []) if name not in PAUSE_POINTS]
        if unknown:
            raise RunError(f"unknown pause points: {', '.join(unknown)}; known: {', '.join(PAUSE_POINTS)}")
        if not self.environment.strip() or not self.owner.strip():
            raise RunError("environment and owner are required")


@dataclass
class RunRecord:
    run_id: str
    created_at: str
    updated_at: str
    status: str  # created | running | paused | succeeded | failed | error | cancelled
    cloud: str
    mode: str
    options: dict[str, Any]
    input_filename: str
    run_dir: str
    paused_before: str | None = None
    pause_point: str | None = None
    error: str | None = None
    event_count: int = 0
    name: str | None = None
    tags: list[str] = field(default_factory=list)
    connection_id: str | None = None
    created_by: str | None = None
    cancel_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        """Tolerate records written by older or newer versions (unknown keys are dropped)."""
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


def build_run_config(base_config: dict[str, Any], options: RunOptions, output_dir: Path | str) -> dict[str, Any]:
    """Apply run options on top of config.yaml the same way the CLI does."""
    cfg = copy.deepcopy(base_config)
    cfg["target_cloud"] = options.cloud.lower()

    generation_cfg = cfg.setdefault("generation", {})
    if not isinstance(generation_cfg, dict):
        generation_cfg = {}
        cfg["generation"] = generation_cfg
    if options.mode:
        generation_cfg["mode"] = options.mode.lower()
    mode = str(generation_cfg.get("mode") or "deterministic").lower()

    llm_cfg = cfg.setdefault("llm", {})
    if not isinstance(llm_cfg, dict):
        llm_cfg = {}
        cfg["llm"] = llm_cfg
    provider_name = (options.llm_provider or str(llm_cfg.get("provider") or "")).lower()
    if mode != "deterministic" and provider_name not in LLM_PROVIDERS:
        raise RunError(f"mode {mode} requires an llm_provider ({', '.join(LLM_PROVIDERS)}) or llm.provider in config")
    if provider_name:
        llm_cfg["provider"] = provider_name
        llm_cfg["model"] = options.llm_model or PROVIDER_DEFAULT_MODELS.get(provider_name, llm_cfg.get("model"))
        if options.llm_base_url:
            llm_cfg["base_url"] = options.llm_base_url

    output_cfg = cfg.setdefault("output", {})
    if not isinstance(output_cfg, dict):
        output_cfg = {}
        cfg["output"] = output_cfg
    output_cfg["base_dir"] = str(output_dir)
    if options.dry_run:
        output_cfg["dry_run"] = True
    output_cfg["llm_review_notes"] = bool(options.llm_review_notes)

    if options.no_mcp:
        mcp_cfg = cfg.setdefault("mcp", {})
        if isinstance(mcp_cfg, dict):
            mcp_cfg["enabled"] = False

    validation_cfg = cfg.setdefault("validation", {})
    if isinstance(validation_cfg, dict):
        if options.skip_validation:
            validation_cfg["run_terraform_validate"] = False
            validation_cfg["run_tflint"] = False
            validation_cfg["run_opa"] = False
        elif options.skip_opa:
            validation_cfg["run_opa"] = False

    required_tags = cfg.setdefault("required_tags", {})
    if isinstance(required_tags, dict):
        required_tags["Environment"] = options.environment
        required_tags["Owner"] = options.owner

    return cfg


def initial_state(discovery: dict[str, Any], cfg: dict[str, Any], cloud: str) -> dict[str, Any]:
    return {
        "discovery_data": discovery,
        "config": cfg,
        "target_provider": TargetProvider(cloud.lower()),
        "quarantine_queue": [],
        "messages": [],
        "retry_count": 0,
        "status": "pending",
        "hcl_output": {},
        "mcp_context": "",
        "validation_result": {},
        "review_notes": "",
    }


class RunStore:
    """Filesystem persistence for run records, inputs, events and artifacts."""

    def __init__(self, runs_dir: Path | str, secret_box: Any | None = None, encrypt_inputs: bool = False) -> None:
        self.root = Path(runs_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Optional encryption at rest for discovery.json (security.encrypt_run_inputs).
        self.secret_box = secret_box
        self.encrypt_inputs = bool(encrypt_inputs)

    def run_dir(self, run_id: str) -> Path:
        _validate_run_id(run_id)
        return self.root / run_id

    def artifacts_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "artifacts"

    def create(self, record: RunRecord, discovery: dict[str, Any]) -> None:
        run_dir = self.run_dir(record.run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "artifacts").mkdir()
        if self.encrypt_inputs:
            if self.secret_box is None or not getattr(self.secret_box, "available", False):
                raise RunError("security.encrypt_run_inputs is on but no secret key is configured")
            (run_dir / "discovery.json.enc").write_text(self.secret_box.encrypt_json(discovery), encoding="utf-8")
        else:
            (run_dir / "discovery.json").write_text(json.dumps(discovery, indent=2, ensure_ascii=True), encoding="utf-8")
        (run_dir / "events.jsonl").write_text("", encoding="utf-8")
        self.save(record)

    def save(self, record: RunRecord) -> None:
        record.updated_at = _now()
        with self._lock:
            _atomic_write_text(
                self.run_dir(record.run_id) / "run.json",
                json.dumps(record.to_dict(), indent=2, ensure_ascii=True),
            )

    def load(self, run_id: str) -> RunRecord:
        path = self.run_dir(run_id) / "run.json"
        if not path.exists():
            raise RunError(f"unknown run: {run_id}")
        last_error: Exception | None = None
        for _ in range(3):  # writes are atomic; this only guards against an exotic partial read
            try:
                return RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, TypeError) as exc:
                last_error = exc
                time.sleep(0.02)
        raise RunError(f"run record for {run_id} is unreadable: {last_error}")

    def load_discovery(self, run_id: str) -> dict[str, Any]:
        encrypted = self.run_dir(run_id) / "discovery.json.enc"
        if encrypted.exists():
            if self.secret_box is None:
                raise RunError(f"run {run_id} input is encrypted but no secret key is configured")
            return self.secret_box.decrypt_json(encrypted.read_text(encoding="utf-8"))
        return json.loads((self.run_dir(run_id) / "discovery.json").read_text(encoding="utf-8"))

    def delete(self, run_id: str) -> None:
        run_dir = self.run_dir(run_id)
        if not run_dir.exists():
            raise RunError(f"unknown run: {run_id}")
        with self._lock:
            shutil.rmtree(run_dir)

    def list(self) -> list[RunRecord]:
        records: list[RunRecord] = []
        for path in self.root.glob("*/run.json"):
            try:
                records.append(RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (ValueError, TypeError):
                continue
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            with (self.run_dir(run_id) / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=True) + "\n")

    def events(self, run_id: str, since: int = 0) -> list[dict[str, Any]]:
        path = self.run_dir(run_id) / "events.jsonl"
        if not path.exists():
            raise RunError(f"unknown run: {run_id}")
        events: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index < since or not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    # A line still being appended by the executing thread; it is complete on the next read.
                    break
        return events

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        base = self.artifacts_dir(run_id)
        if not base.exists():
            return []
        return [
            {"path": str(path.relative_to(base)).replace("\\", "/"), "size": path.stat().st_size}
            for path in sorted(base.rglob("*"))
            if path.is_file()
        ]

    def read_artifact(self, run_id: str, relative_path: str) -> str:
        base = self.artifacts_dir(run_id)
        target = (base / relative_path).resolve()
        if base.resolve() not in target.parents or not target.is_file():
            raise RunError(f"unknown artifact: {relative_path}")
        return target.read_text(encoding="utf-8")


class MigrationRuntime:
    """Create, start, pause, inspect, patch, resume and re-run migration runs."""

    def __init__(
        self,
        base_config: dict[str, Any],
        runs_dir: Path | str | None = None,
        checkpoint_db: Path | str | None = None,
        secret_box: Any | None = None,
    ) -> None:
        self.base_config = base_config
        runtime_cfg = base_config.get("runtime") if isinstance(base_config.get("runtime"), dict) else {}
        security_cfg = base_config.get("security") if isinstance(base_config.get("security"), dict) else {}
        self.store = RunStore(
            runs_dir or runtime_cfg.get("runs_dir") or "output/runs",
            secret_box=secret_box,
            encrypt_inputs=bool(security_cfg.get("encrypt_run_inputs", False)),
        )
        self._cancel_requested: set[str] = set()
        self.default_pause_points = [
            str(item) for item in (runtime_cfg.get("default_pause_points") or []) if str(item) in PAUSE_POINTS
        ]
        db_setting = checkpoint_db if checkpoint_db is not None else runtime_cfg.get("checkpoint_db")
        self._checkpoint_db = Path(str(db_setting)).expanduser() if db_setting else None
        self._checkpointer: Any | None = None
        self._lock = threading.RLock()
        self._active: set[str] = set()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def create_run(
        self,
        discovery: dict[str, Any],
        options: RunOptions,
        input_filename: str = "discovery.json",
        name: str | None = None,
        tags: list[str] | None = None,
        connection_id: str | None = None,
        created_by: str | None = None,
    ) -> RunRecord:
        options.validate()
        validate_discovery_payload(discovery)  # raises ValueError with a clear message

        run_id = _new_run_id()
        run_dir = self.store.run_dir(run_id)
        cfg = build_run_config(self.base_config, options, run_dir / "artifacts")

        if options.pause_points is None:
            options.pause_points = list(self.default_pause_points)

        record = RunRecord(
            run_id=run_id,
            created_at=_now(),
            updated_at=_now(),
            status="created",
            cloud=options.cloud.lower(),
            mode=str(cfg.get("generation", {}).get("mode", "deterministic")),
            options=asdict(options),
            input_filename=input_filename,
            run_dir=str(run_dir),
            name=_clean_name(name),
            tags=_clean_tags(tags),
            connection_id=connection_id or None,
            created_by=created_by,
        )
        self.store.create(record, discovery)
        (run_dir / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
        logger.info("runtime: created run {} ({} / {})", run_id, record.cloud, record.mode)
        return record

    def start(self, run_id: str) -> RunRecord:
        record = self.store.load(run_id)
        if record.status != "created":
            raise RunError(f"run {run_id} is {record.status}; only a created run can be started")
        cfg = self._load_config(run_id)
        state = initial_state(self.store.load_discovery(run_id), cfg, record.cloud)
        return self._execute(record, state)

    def resume(self, run_id: str) -> RunRecord:
        record = self.store.load(run_id)
        if record.status != "paused":
            raise RunError(f"run {run_id} is {record.status}; only a paused run can be resumed")
        return self._execute(record, None)

    def rerun_from(self, run_id: str, node: str) -> RunRecord:
        """Fork the run from the last checkpoint taken just before `node` and continue."""
        if node not in NODE_ORDER:
            raise RunError(f"unknown node {node}; known: {', '.join(NODE_ORDER)}")
        record = self.store.load(run_id)
        if record.status in {"running", "created"}:
            raise RunError(f"run {run_id} is {record.status}; it cannot be re-run yet")

        graph = self._graph(record)
        # Materialize the history: the checkpointer's generator holds its connection lock
        # while suspended, so breaking out of it early would deadlock the next write.
        history = list(graph.get_state_history(self._thread_config(run_id)))
        checkpoint_config = next(
            (snapshot.config for snapshot in history if snapshot.next and snapshot.next[0] == node),
            None,
        )
        if checkpoint_config is None:
            raise RunError(f"run {run_id} has no checkpoint before {node}")

        self.store.append_event(run_id, _event("rerun", node=node, summary={"from_checkpoint": checkpoint_config["configurable"].get("checkpoint_id")}))
        return self._execute(record, None, config=checkpoint_config)

    def cancel(self, run_id: str) -> RunRecord:
        """Stop a run. An executing run stops after the current node; created or paused runs
        are marked cancelled immediately. Cancelled runs can be re-run from a checkpoint."""
        record = self.store.load(run_id)
        if record.status in TERMINAL_STATUSES:
            raise RunError(f"run {run_id} is already {record.status}")
        with self._lock:
            executing = run_id in self._active
            if executing:
                self._cancel_requested.add(run_id)
        record.cancel_requested = True
        if not executing:
            record.status = "cancelled"
            record.paused_before = None
            record.pause_point = None
            self.store.append_event(run_id, _event("cancelled", summary={"while": "idle"}))
        self.store.save(record)
        return record

    def update_run(
        self,
        run_id: str,
        name: str | None = None,
        tags: list[str] | None = None,
        connection_id: str | None = None,
        clear_connection: bool = False,
    ) -> RunRecord:
        record = self.store.load(run_id)
        if name is not None:
            record.name = _clean_name(name)
        if tags is not None:
            record.tags = _clean_tags(tags)
        if clear_connection:
            record.connection_id = None
        elif connection_id:
            record.connection_id = connection_id
        self.store.save(record)
        return record

    def delete_run(self, run_id: str) -> None:
        record = self.store.load(run_id)
        with self._lock:
            if run_id in self._active:
                raise RunError(f"run {run_id} is executing; cancel it first")
        self.store.delete(run_id)
        checkpointer = self._checkpointer
        delete_thread = getattr(checkpointer, "delete_thread", None)
        if callable(delete_thread):
            try:
                delete_thread(run_id)
            except Exception as exc:  # pragma: no cover - best effort cleanup
                logger.warning("runtime: could not delete checkpoints for {}: {}", run_id, exc)
        logger.info("runtime: deleted run {} ({})", run_id, record.status)

    # ── inspection and control ────────────────────────────────────────────────

    def get_run(self, run_id: str) -> RunRecord:
        return self.store.load(run_id)

    def list_runs(self) -> list[RunRecord]:
        return self.store.list()

    def events(self, run_id: str, since: int = 0) -> list[dict[str, Any]]:
        return self.store.events(run_id, since=since)

    def get_state(self, run_id: str) -> dict[str, Any]:
        """Current graph state as JSON-safe data (CIM models dumped, enums as values)."""
        record = self.store.load(run_id)
        snapshot = self._graph(record).get_state(self._thread_config(run_id))
        values = dict(snapshot.values or {})
        values.pop("config", None)  # large and already in config.json
        return {
            "run_id": run_id,
            "status": record.status,
            "next": list(snapshot.next or ()),
            "values": _jsonable(values),
        }

    def patch_state(self, run_id: str, values: dict[str, Any]) -> RunRecord:
        """Replace state keys while the run is paused (for example an edited sized_cim)."""
        record = self.store.load(run_id)
        if record.status != "paused" or not record.paused_before:
            raise RunError(f"run {run_id} is {record.status}; state can only be patched while paused")

        unknown = sorted(set(values) - set(PATCHABLE_KEYS))
        if unknown:
            raise RunError(f"keys not patchable: {', '.join(unknown)}; allowed: {', '.join(PATCHABLE_KEYS)}")

        validated: dict[str, Any] = {}
        for key, raw in values.items():
            model = PATCHABLE_KEYS[key]
            if model is None:
                validated[key] = raw
                continue
            try:
                validated[key] = model.model_validate(raw) if not isinstance(raw, model) else raw
            except Exception as exc:
                raise RunError(f"invalid {key}: {exc}") from exc

        graph = self._graph(record)
        previous_node = NODE_ORDER[max(NODE_ORDER.index(record.paused_before) - 1, 0)]
        graph.update_state(self._thread_config(run_id), validated, as_node=previous_node)

        self.store.append_event(run_id, _event("patch", node=record.paused_before, summary={"keys": sorted(validated)}))
        self.store.save(record)
        return record

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        self.store.load(run_id)
        return self.store.artifacts(run_id)

    def read_artifact(self, run_id: str, relative_path: str) -> str:
        self.store.load(run_id)
        return self.store.read_artifact(run_id, relative_path)

    # ── execution ─────────────────────────────────────────────────────────────

    def _execute(self, record: RunRecord, state: dict[str, Any] | None, config: dict[str, Any] | None = None) -> RunRecord:
        run_id = record.run_id
        with self._lock:
            if run_id in self._active:
                raise RunError(f"run {run_id} is already executing")
            self._active.add(run_id)

        graph = self._graph(record)
        thread_config = config or self._thread_config(run_id)
        record.status = "running"
        record.paused_before = None
        record.pause_point = None
        record.error = None
        self.store.save(record)
        self.store.append_event(run_id, _event("start" if state is not None else "resume", summary={"paused_before": None}))

        seen_messages = 0 if state is not None else self._message_count(graph, thread_config)
        cancelled = False
        try:
            for update in graph.stream(state, thread_config, stream_mode="updates"):
                for node, payload in update.items():
                    if node == "__interrupt__":
                        continue
                    seen_messages = self._record_node_event(record, node, payload, seen_messages)
                with self._lock:
                    cancelled = run_id in self._cancel_requested
                if cancelled:
                    break
        except Exception as exc:
            record.status = "error"
            record.error = f"{exc.__class__.__name__}: {exc}"
            self.store.append_event(run_id, _event("error", summary={"error": record.error}))
            logger.exception("runtime: run {} failed", run_id)
            self.store.save(record)
            with self._lock:
                self._active.discard(run_id)
                self._cancel_requested.discard(run_id)
            return record

        snapshot = graph.get_state(self._thread_config(run_id))
        if cancelled:
            record.status = "cancelled"
            record.cancel_requested = True
            self.store.append_event(run_id, _event("cancelled", node=snapshot.next[0] if snapshot.next else None, summary={"while": "executing"}))
        elif snapshot.next:
            record.status = "paused"
            record.paused_before = snapshot.next[0]
            record.pause_point = NODE_TO_PAUSE_POINT.get(record.paused_before)
            self.store.append_event(run_id, _event("paused", node=record.paused_before, summary={"pause_point": record.pause_point}))
        else:
            final_status = str((snapshot.values or {}).get("status") or "unknown")
            record.status = "succeeded" if final_status == "succeeded" else "failed"
            self.store.append_event(run_id, _event("end", summary=_summarize(snapshot.values or {})))

        self.store.save(record)
        with self._lock:
            self._active.discard(run_id)
            self._cancel_requested.discard(run_id)
        return record

    def _record_node_event(self, record: RunRecord, node: str, payload: Any, seen_messages: int) -> int:
        values = payload if isinstance(payload, dict) else {}
        messages = values.get("messages") if isinstance(values.get("messages"), list) else []
        new_messages = [str(item) for item in messages[seen_messages:]]
        seen = max(seen_messages, len(messages))
        event = _event("node", node=node, summary=_summarize(values), messages=new_messages)
        record.event_count += 1
        self.store.append_event(record.run_id, event)
        return seen

    def _message_count(self, graph: Any, thread_config: dict[str, Any]) -> int:
        snapshot = graph.get_state(thread_config)
        messages = (snapshot.values or {}).get("messages")
        return len(messages) if isinstance(messages, list) else 0

    def _graph(self, record: RunRecord) -> Any:
        pause_nodes = [PAUSE_POINTS[name] for name in (record.options.get("pause_points") or []) if name in PAUSE_POINTS]
        return graph_module.build_graph(checkpointer=self._get_checkpointer(), interrupt_before=pause_nodes)

    def _get_checkpointer(self) -> Any:
        with self._lock:
            if self._checkpointer is None:
                from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
                from langgraph.checkpoint.sqlite import SqliteSaver

                serde = JsonPlusSerializer(allowed_msgpack_modules=list(_CHECKPOINT_TYPES))
                if self._checkpoint_db:
                    self._checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(str(self._checkpoint_db), check_same_thread=False)
                else:
                    conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._checkpointer = SqliteSaver(conn, serde=serde)
            return self._checkpointer

    def _load_config(self, run_id: str) -> dict[str, Any]:
        return json.loads((self.store.run_dir(run_id) / "config.json").read_text(encoding="utf-8"))

    @staticmethod
    def _thread_config(run_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": run_id}}


# ── helpers ───────────────────────────────────────────────────────────────────


def _summarize(values: dict[str, Any]) -> dict[str, Any]:
    cim = values.get("sized_cim") or values.get("cim")
    validation = values.get("validation_result") if isinstance(values.get("validation_result"), dict) else {}
    quarantine = values.get("quarantine_queue") if isinstance(values.get("quarantine_queue"), list) else []
    hcl_output = values.get("hcl_output") if isinstance(values.get("hcl_output"), dict) else {}
    summary: dict[str, Any] = {
        "status": values.get("status"),
        "quarantined": len(quarantine),
        "hcl_files": len(hcl_output),
    }
    if cim is not None:
        summary["compute_units"] = len(getattr(cim, "compute_units", []) or [])
        summary["clusters"] = len(getattr(cim, "clusters", []) or [])
        topology = getattr(cim, "network_topology", None)
        summary["switches"] = len(getattr(topology, "distributed_switches", []) or [])
    if validation:
        summary["validation_passed"] = bool(validation.get("passed"))
        summary["validation_errors"] = len(validation.get("errors") or [])
    compliance = values.get("compliance_result") if isinstance(values.get("compliance_result"), dict) else {}
    compliance_summary = compliance.get("summary") if isinstance(compliance.get("summary"), dict) else {}
    if compliance_summary:
        summary["compliance_failed"] = int(compliance_summary.get("failed") or 0)
        summary["compliance_advisory"] = int(compliance_summary.get("advisory") or 0)
    return summary


def _event(event_type: str, node: str | None = None, summary: dict[str, Any] | None = None, messages: list[str] | None = None) -> dict[str, Any]:
    return {
        "ts": _now(),
        "type": event_type,
        "node": node,
        "summary": summary or {},
        "messages": messages or [],
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file and rename so readers never observe a truncated file."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_name(name: str | None) -> str | None:
    text = " ".join(str(name).split()) if name else ""
    return text[:120] or None


def _clean_tags(tags: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    for raw in tags or []:
        tag = "-".join(str(raw).strip().lower().split())[:40]
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned[:20]


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def _validate_run_id(run_id: str) -> None:
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise RunError(f"invalid run id: {run_id!r}")


__all__ = [
    "GENERATION_MODES",
    "MigrationRuntime",
    "NODE_ORDER",
    "PAUSE_POINTS",
    "RunError",
    "RunOptions",
    "RunRecord",
    "RunStore",
    "TERMINAL_STATUSES",
    "build_run_config",
    "initial_state",
    "iter_nodes",
]


def iter_nodes() -> Iterator[str]:
    yield from NODE_ORDER

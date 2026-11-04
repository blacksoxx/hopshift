# Runtime And API

`agent/runtime.py` is the service layer the API and UI drive. The CLI's `terragen` shares its
config-override logic but still runs the graph in one shot.

## Runs

A run is a folder under `runtime.runs_dir` (default `output/runs`):

```
<runs_dir>/<run_id>/run.json        metadata and lifecycle status
<runs_dir>/<run_id>/config.json     the effective config for this run
<runs_dir>/<run_id>/discovery.json  the input payload
<runs_dir>/<run_id>/events.jsonl    one event per node, pause, patch, re-run, error, end
<runs_dir>/<run_id>/artifacts/      the reporter's output (HCL, quarantine report, notes)
```

LangGraph checkpoints live in `runtime.checkpoint_db` (SQLite) keyed by run id, which is what
makes pause, resume, state patching and re-run possible across process restarts.

Lifecycle: `created -> running -> paused | succeeded | failed | error`. A paused run resumes into
`running` again.

## Pause points

Named so the UI never needs node names:

| Pause point | Pauses before | Purpose |
|---|---|---|
| `review_cim` | `hcl_generator` | inspect and edit the sized CIM before anything is generated |
| `approve_output` | `reporter` | approve before any file is written to artifacts/ |

`runtime.default_pause_points` applies to runs created without explicit pause points.

While paused, `patch_state` accepts `sized_cim`, `cim` and `quarantine_queue`. CIM values are
validated against the Pydantic model before they are written into the checkpoint.

`rerun_from(node)` forks the run at the last checkpoint taken before that node and continues
from there; the previous history is kept.

## Events

Each line of `events.jsonl` is `{ts, type, node, summary, messages}` with `type` one of
`start`, `node`, `paused`, `patch`, `resume`, `rerun`, `error`, `end`. `summary` carries counts
(compute units, quarantined, HCL files, validation outcome) and `messages` the run messages added
by that node.

## HTTP API

Start with `vma serve` (needs the `api` extra: `pip install '.[api]'`). Interactive docs at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/meta`, `/config` | liveness, enums for the UI, effective base config |
| GET | `/runs` | list runs |
| POST | `/runs` | create a run from `{discovery, options, input_filename?, start?}` |
| GET | `/runs/{id}` | run record plus `executing` |
| POST | `/runs/{id}/start` | start a created run (202) |
| POST | `/runs/{id}/resume` | approve / continue a paused run (202) |
| POST | `/runs/{id}/rerun` | `{node}`: fork from the checkpoint before that node (202) |
| GET | `/runs/{id}/state` | current graph state, JSON-safe, without config |
| PATCH | `/runs/{id}/state` | `{values}`: patch state while paused |
| GET | `/runs/{id}/events?since=N` | events after index N |
| GET | `/runs/{id}/events/stream` | server-sent events until the run pauses or ends |
| GET | `/runs/{id}/artifacts` | list artifact files |
| GET | `/runs/{id}/artifacts/{path}` | artifact content |
| POST | `/assess` | synchronous risk assessment `{discovery, cloud}` |

`options` mirrors the CLI flags: `cloud`, `environment`, `owner`, `mode`, `llm_provider`,
`llm_model`, `llm_base_url`, `skip_validation`, `skip_opa`, `no_mcp`, `dry_run`, `pause_points`.

Errors: unknown run 404, lifecycle or validation problems 400, a second start on an executing
run 409. Runs execute in a small thread pool; the API process must stay up for a run to progress.

Not yet: authentication, multipart upload, cancellation. The API binds to localhost by default.

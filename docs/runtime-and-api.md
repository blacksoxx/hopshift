# Run runtime

`hopshift/pipeline/runtime.py` is the service layer the API and UI drive. The CLI's `terragen` shares its
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

The endpoint reference moved to [api.md](api.md). In short: everything lives under `/api`,
authentication is a session cookie or a `hs_` bearer token, roles are viewer / operator /
admin, runs execute in a thread pool and are observed through polling or server-sent events,
and the built UI is served at `/`.

# Web UI

A React + Vite front-end over the HTTP API (see runtime-and-api.md). Source lives in `ui/`.

## Screens

- **Runs**: every run with status, pause point, cloud, mode and input; refreshes every few seconds.
- **New run**: pick a discovery JSON (parsed in the browser, VM count shown), target cloud, generation mode, LLM provider for llm/hybrid, Environment and Owner tags, skip flags, dry run, and which pause points to stop at. Starts the run and opens it.
- **Run detail**: status and actions (Approve and continue / Approve and write output while paused, Re-run from a node when finished), the node timeline, and four tabs:
  - Overview: counts, validation errors and warnings, quarantine list with reasons.
  - CIM: compute units, clusters and topology. Editable (name, vCPU, RAM, image ref, or raw JSON) while the run is paused at `review_cim`; Save writes the edited CIM into the paused run.
  - Artifacts: generated files with a viewer, available once the output has been approved.
  - Log: the event stream with each node's messages. Live while the run executes (server-sent events).
- **Assess**: deterministic risk report for a discovery file without creating a run.
- **Settings**: effective server configuration and pipeline metadata (read-only).

Routing uses URL hashes (`/#/runs/<id>`) so the built app can be served by FastAPI at `/` while
the API keeps `/api/*`.

## Develop

```bash
cd ui
npm install
npm run dev          # http://localhost:5173, proxies /api to http://127.0.0.1:8080
```

Run the API separately from the repository root: `vma serve` (default port 8080).

## Build and serve

```bash
cd ui && npm run build     # type-checks, writes ui/dist
vma serve                  # serves ui/dist at / and the API at /api
```

## Tests

- `npm test`: Vitest component and client tests (jsdom, API mocked).
- `npm run e2e`: Playwright against the real server. Builds must exist (`npm run build`); the
  config starts `vma serve` on port 8765 from the repository root, uploads
  `tests/fixtures/discovery_multi_vm.json`, pauses at `review_cim`, edits a VM name, approves
  twice and checks the renamed Terraform file in the artifacts. First run: `npx playwright install chromium`.

The end-to-end run creates real runs under `output/runs/`. If an LLM credential is present the
reporter calls the model for the review notes; set `output.write_review_notes: false` or remove
the credential to keep end-to-end runs offline.

## Not yet

Authentication, config editing, cancellation of a running job, per-VM quarantine overrides,
and a topology graph view. The UI assumes a single user on a trusted network.

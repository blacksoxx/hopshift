# The web UI

A single-page application (React 19, Vite, TypeScript, Tailwind v4, Radix primitives, motion)
served by the API from `ui/dist`. It talks only to `/api`; it holds no secrets and no business
logic. Light and dark themes follow the system or the toggle in the top bar.

The UI knows nothing about particular sources or targets. Everything it shows about them, names,
blurbs, support tiers, which discovery schema belongs to which source, which connection
provider a target deploys through, comes from the registries the server exposes on
`GET /api/meta` (`targets` and `sources`) and from the connection catalog on
`GET /api/connections/methods`. A target or source added as a plugin appears in the UI without
a code change.

## Pages

| Route | What it is for |
|---|---|
| `/setup` | Shown once, while no user exists: create the first administrator. |
| `/login` | Password sign-in, second-factor step, single sign-on button when OIDC is configured. |
| `/` | Dashboard: run counts, success rate, 30-day activity, runs waiting for approval, connections, security posture. |
| `/runs` | All runs with search, status and target filters, tag chips; cancel and delete from the row menu. |
| `/runs/new` | Four-step wizard: upload the discovery JSON (the source that accepts it is named, with counts of compute units and clusters), choose the target and options, pick a connection, review and start. |
| `/runs/:id` | Run detail: live timeline, overview (stats, validation, quarantine, review notes), CIM editor (table with inline edits, bulk actions, raw JSON), artifacts (file tree, highlighted viewer, diff against another run, zip download), deploy (variables, plan, apply and destroy with typed confirmation, live logs, state), compliance report, event log. |
| `/assess` | Readiness assessment of an inventory without creating a run: risk per workload, charts, CSV and Markdown export. |
| `/connections` | Stored connections: add with a provider → method → form flow driven by the catalog, test, device-code sign-in, replace secrets, delete. |
| `/settings` | General (editable configuration), users, API tokens, audit log, security posture, profile (password, second factor). |
| `/audit` | The audit log with filters, chain verification and export (admin). |

Roles shape what is visible: viewers read, operators run and approve, admins manage users,
connections and settings.

## Targets, sources and tiers

The wizard's target step renders one card per entry in `meta.targets`: the label, the one-line
blurb and a tier badge. Runs lists, the dashboard, the run header, the compliance and
artifacts tabs and the assessment page show the same labels through the `useTargets()` hook
(`labelOf(name)`, `providerOf(name)`) and the `TargetBadge` component; the bare name,
upper-cased, is the fallback while the registry loads or for a target the server no longer
knows.

Tier badges use the same three values as the registries:

| Tier | Badge | Meaning |
|---|---|---|
| `tested` | green | Covered by the integration suite on every release: the rendered Terraform passes `terraform validate`, `tflint` and the policy checks. |
| `validated` | blue | Renders and passes `terraform validate` and the policy checks; not yet covered end to end by the integration suite. |
| `experimental` | amber | Provided by a plugin or still maturing. Review the generated output carefully before deploying it. |

The discovery step reads `metadata.schema_name` from the uploaded file and matches it against
`meta.sources[].schema_names` (case-insensitively). The matching source is named next to the
upload; a file without a schema name, or with one no registered source accepts, shows an error
listing the registered sources and keeps **Continue** disabled. The review step names both the
source and the target.

Connections render from the catalog: provider labels come from `GET /api/connections/methods`
and from `provider_label` on each stored connection. The four providers that ship with hopshift
keep hand-written brand tints and identity rules (the ARN for AWS, the subscription for Azure,
the project for Google Cloud and OpenStack). Any other provider gets a neutral monogram tile
derived from its key, an identity summary made of the first two scalar values the test
returned, and a note pointing at the target's documentation where the Terraform environment
variables would be listed.

## Keyboard

| Keys | Action |
|---|---|
| `⌘K` / `Ctrl+K` | Command palette: jump to pages and recent runs, switch theme |
| `g` then `d` / `r` / `n` / `a` / `c` / `s` | Dashboard, Runs, New run, Assess, Connections, Settings |
| `1`–`6` on a run page | Switch tabs |
| `Esc` | Close dialogs and the palette |

## Live updates

Run pages subscribe to server-sent events for the log and timeline, poll the run status every
two seconds as a safety net while a run executes, and resubscribe after a dropped stream.
Deployment logs stream the same way. Nothing on a page blocks while work is running.

## Building and testing

```bash
cd ui
npm ci
npm run dev            # Vite on :5173, proxies /api to :8080 (VITE_API_PROXY to change)
npm run build          # production bundle in ui/dist (served by `vma serve`)
npx tsc --noEmit       # type check
npx vitest run         # unit tests (jsdom, Testing Library)
npx playwright test    # end-to-end: starts an isolated server through e2e/serve.py
```

`npx playwright test` builds nothing: run `npm run build` first. To test an already running
server (for example the Docker stack) set `PLAYWRIGHT_BASE_URL=http://127.0.0.1:8080`; the
suite creates the first administrator when the server is fresh and signs in otherwise. The
isolated server uses `../.venv/bin/python` by default; set `HOPSHIFT_PYTHON` to another
interpreter (a git worktree, for instance, has no `.venv` of its own).

`node scripts/screenshots.mjs <base-url>` regenerates the PNGs under `docs/images/` from a
running server (see the header of the script).

## Design system

Components under `ui/src/components/ui` are owned by the repository (buttons, inputs, badges,
cards, dialogs, menus, tooltips, tabs, switches, selects, toasts, tables, alerts, empty states,
stats). Tokens live in `ui/src/styles/globals.css` and are exposed as Tailwind colours
(`bg-background`, `text-muted-foreground`, `border-border`, `text-primary`, `text-success`,
`text-warning`, `text-destructive`). Fonts (Inter, JetBrains Mono) are self-hosted so the strict
Content-Security-Policy needs no external origins.

The brand is the wordmark `hopshift` with the tagline *migrate anything from X to Y*
(`ui/src/components/Logo.tsx`); the mark is an inline SVG of a workload hopping from its origin
to an arrowhead, drawn with theme tokens so it reads at 16px and 40px on light and dark. The
favicon (`ui/public/favicon.svg`) is the same drawing with fixed colours.

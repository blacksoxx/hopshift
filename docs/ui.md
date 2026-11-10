# The web UI

A single-page application (React 19, Vite, TypeScript, Tailwind v4, Radix primitives, motion)
served by the API from `ui/dist`. It talks only to `/api`; it holds no secrets and no business
logic. Light and dark themes follow the system or the toggle in the top bar.

## Pages

| Route | What it is for |
|---|---|
| `/setup` | Shown once, while no user exists: create the first administrator. |
| `/login` | Password sign-in, second-factor step, single sign-on button when OIDC is configured. |
| `/` | Dashboard: run counts, success rate, 30-day activity, runs waiting for approval, connections, security posture. |
| `/runs` | All runs with search, status and target filters, tag chips; cancel and delete from the row menu. |
| `/runs/new` | Four-step wizard: upload the discovery JSON (summary of VMs, switches, clusters, vCenter), choose the target and options, pick a connection, review and start. |
| `/runs/:id` | Run detail: live timeline, overview (stats, validation, quarantine, review notes), CIM editor (table with inline edits, bulk actions, raw JSON), artifacts (file tree, highlighted viewer, diff against another run, zip download), deploy (variables, plan, apply and destroy with typed confirmation, live logs, state), compliance report, event log. |
| `/assess` | Readiness assessment of an inventory without creating a run: risk per VM, charts, CSV and Markdown export. |
| `/connections` | Connections: add with a provider → method → form flow driven by the catalog, test, device-code sign-in, replace secrets, delete. |
| `/settings` | General (editable configuration), users, API tokens, audit log, security posture, profile (password, second factor). |
| `/audit` | The audit log with filters, chain verification and export (admin). |

Roles shape what is visible: viewers read, operators run and approve, admins manage users,
connections and settings.

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
npm run build          # production bundle in ui/dist (served by `hopshift serve`)
npx tsc --noEmit       # type check
npx vitest run         # unit tests (jsdom, Testing Library)
npx playwright test    # end-to-end: starts an isolated server through e2e/serve.py
```

`npx playwright test` builds nothing: run `npm run build` first. To test an already running
server (for example the Docker stack) set `PLAYWRIGHT_BASE_URL=http://127.0.0.1:8080`; the
suite creates the first administrator when the server is fresh and signs in otherwise.

## Design system

Components under `ui/src/components/ui` are owned by the repository (buttons, inputs, badges,
cards, dialogs, menus, tooltips, tabs, switches, selects, toasts, tables, alerts, empty states,
stats). Tokens live in `ui/src/styles/globals.css` and are exposed as Tailwind colours
(`bg-background`, `text-muted-foreground`, `border-border`, `text-primary`, `text-success`,
`text-warning`, `text-destructive`). Fonts (Inter, JetBrains Mono) are self-hosted so the strict
Content-Security-Policy needs no external origins.

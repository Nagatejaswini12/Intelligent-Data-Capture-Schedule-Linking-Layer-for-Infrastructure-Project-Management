# Frontend Architecture

[← Master plan](../PROJECT_MASTER_PLAN.md) · Related: [Backend API](BACKEND_API.md) · [End-to-end workflow](../plan/END_TO_END_WORKFLOW.md)

## 0. Implemented (Phase 7)

React 19 + TypeScript + Vite in `web/`, served by FastAPI from `web/dist` after `npm run build` (one origin, no CORS). Dependencies: `react`, `react-dom`; dev only: `vite`, `@vitejs/plugin-react`, `typescript`, `@types/react`, `@types/react-dom`, `vitest`. No router, chart, state or CSS library: hash routing (~20 lines), CSS-only bars from real counts, plain CSS tokens (dark default, light toggle), `fetch` wrapper. Recharts and React Router from the plan below were not needed.

```
web/src/
├── api/client.ts      fetch wrapper: base URL (VITE_API_BASE_URL, default same origin), X-API-Key, problem+json -> ApiError
├── api/p2e.ts         typed calls to the existing API (the backend contract test parses this file)
├── hooks/useApi.ts    load / error / reload; hooks/useStream.ts  live snapshot from the Phase 5 SSE stream via fetch
├── components/        ui.tsx (Card, Kpi, Badge, Bars, StackBars, CompareBars, Flow, Modal, Async states), Evidence.tsx
├── pages/             Overview, Reports, Linking, Agent, Schedule, Watch, Analytics, Memory, Audit, Demo
├── state.tsx          project, as-of date, live snapshot      utils/  format.ts, route.ts
├── styles/app.css     tokens + layout                         test/fixtures/  real API responses (synthetic project)
```

| Screen | Route | Backend used |
|---|---|---|
| Overview | `#/overview` | analytics/dashboard, analytics/dataset, links totals, documents, events, analytics/delays |
| Field Reports | `#/reports` | documents (+ upload → process → link run), document status, events, links, events/{id}/evidence |
| Activity Linking | `#/linking` | links (filters), links/{id}, events/{id}; approve / choose another, reject, hold (send to review), new activity; tab "Blocked actuals": review + override |
| Time Agent | `#/agent` | agent/messages (interpretation, clarification answers, link result, checklist) |
| Schedule | `#/schedule` | hierarchy, analytics/dataset, links (conflicts); apply (dry run → apply), export CSV / MSPDI |
| Silent Activity Watch | `#/watch` | watch/silent (days, discipline, area); link to the Time Agent checklist |
| Analytics | `#/analytics` | analytics/dashboard, productivity, delays, dataset.csv |
| Project Memory | `#/memory` | memory/ask (clickable citations: activity → schedule, report → evidence, document → reports), knowledge |
| Audit Trail | `#/audit` | audit (filters), audit/{id}/undo, evidence of the source reports |
| Demo Flow | `#/demo` | agent → approve (confirm + apply) → dataset row → audit → memory/ask, all live |

**Auth.** Sign-in asks for a role API key (from `P2E_API_KEYS` on the server) and keeps it in `sessionStorage` for the tab only; nothing secret is in the build or in `.env` files (`web/.env.example`). Role errors (403) are shown as such.

**States.** Every view has loading / error (with retry) / empty states; a failed call is shown as an error, never replaced by sample data. Phase 3.2 "source unavailable" evidence is shown with its stored metadata. The top bar shows a live/offline indicator; pages refetch when the backend snapshot changes.

**Run**

```
# 1. backend (once): environment + data
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python scripts\phase1\init_database.py
.venv\Scripts\python scripts\phase2\ingest_documents.py
.venv\Scripts\python scripts\phase3\link_events.py

# 2. frontend (once): install + build -> web\dist (served by FastAPI at /)
cd web; npm install; npm run build; cd ..

# 3. run: choose your own keys (16+ characters), never commit them
$env:P2E_API_KEYS = "planner:<planner key>,supervisor:<supervisor key>"
.venv\Scripts\python -m uvicorn p2e.main:app --port 8000
# open http://localhost:8000 , sign in with one of the keys, set "As of" to 2026-09-16 for the synthetic project

# development with hot reload instead of step 2 (proxies /api to :8000)
cd web; npm run dev        # http://localhost:5173
```

**Demo (≈ 3 minutes, synthetic project, As of = 2026-09-16).** Overview (flow strip and KPIs) → Demo Flow: send "PT-1102 loop check started today at 9 am" (instrumentation) → extraction + matched `INS-A1-PT1102-LCK` + confidence → Confirm and apply → schedule row now in progress → audit entry with the source report → ask "What is the status of PT-1102 loop check?" → answer with citation. Then show Activity Linking (a conflict case with both reports and evidence), Silent Activity Watch, Analytics and the Audit undo.

**Tests.** `cd web; npm test` (Vitest: API client, error mapping, routing, SSE parsing, formatting, component rendering with captured real responses). `npm run build` type-checks (strict) and builds. Backend: `tests/test_phase7.py` (new endpoints, static serving, contract: every route in `api/p2e.ts` exists).

**Limitations.** No browser end-to-end test in CI (pages were checked against a running backend during development); no virtualised tables (fine at 317 activities); no voice input; single project selector (first project); live updates are snapshot-triggered refetches (the stream is polled server-side every second).

## 1. Stack

| Concern | Choice | Why |
|---|---|---|
| Framework | React 18+ with TypeScript, built by Vite | Team familiarity, fast dev server, static build served by FastAPI |
| Routing | React Router | 7 screens |
| Data fetching | `fetch` wrapper + small hooks. Add TanStack Query only if caching/refetch logic grows | Fewer dependencies |
| Live updates | Native `EventSource` (SSE) | No websocket library needed |
| Voice | Native Web Speech API (`SpeechRecognition`) | Zero dependency. Works in Chrome/Edge. Text fallback everywhere |
| Charts | Recharts (one chart library) | Dashboard only |
| Plan vs actual timeline | Custom CSS-grid/SVG bars | ~100 lines. A Gantt library is unnecessary for read-only bars |
| Styling | Plain CSS with design tokens (CSS variables), light/dark | No CSS framework required |
| Tables | Native `<table>` with sticky headers, virtualized only if > 2k rows | |

## 2. Users → screens

| Screen | Route | Primary user | Key elements |
|---|---|---|---|
| Sign-in / role | `/` | all | Pick demo user (supervisor-piping, supervisor-electrical, planner, PM) |
| **Time agent** | `/agent` | supervisor | Mobile-first chat, mic button, quick-reply chips for disambiguation, confirmation card, "undo" |
| **Upload** | `/upload` | supervisor/planner | Drag-drop DPR/spreadsheet, paste text, live processing timeline (received → extracted N → linked M → applied K / review R / unmatched U) |
| **Review queue** | `/review` | planner | Two tabs: *Needs review* and *Unmatched/New*. Each card: source evidence with highlighted span, top-3 candidates with score bars and reasons, actions (approve, pick other, create new under suggested WBS, reject). Keyboard shortcuts (A/1/2/3/N/R) |
| **Schedule** | `/schedule` | planner/PM | WBS tree + table: plan vs actual dates, status, confidence badge, source count. Row → drawer with evidence and audit trail. Timeline bars. Live flash on SSE update. Export buttons |
| **Dashboard** | `/dashboard` | PM | KPIs by discipline, slip distribution, reporting freshness heatmap (discipline × day), review backlog, delay causes |
| **Memory** | `/memory` | planner | Ask a question → answer with clickable citations. Browse knowledge entries. OKF export (stretch) |
| **Aliases** (admin) | `/aliases` | planner | Learned phrase→activity list. Delete wrong ones |

## 3. Component structure

```
web/src/
├── api/            client.ts (fetch + auth header + error mapping), types.ts (mirrors Pydantic schemas)
├── hooks/          useStream(pid), useSpeech(), useApi()
├── components/     ConfidenceBadge, EvidenceSnippet, CandidateList, TimelineBar,
│                   AuditTrail, ProcessingTimeline, ChatBubble, MicButton, KpiTile
├── pages/          Agent, Upload, Review, Schedule, Dashboard, Memory, Aliases, SignIn
└── styles/         tokens.css, base.css
```

Types: hand-written `types.ts` matching the API for the hackathon. Production: generate from FastAPI's OpenAPI schema.

## 4. Key interaction designs

### Time agent (mobile)
```
┌───────────────────────────────┐
│ ◀  Time agent   Piping · A3   │
├───────────────────────────────┤
│  ▸ started HT on line 1203    │  (user)
│ ┌───────────────────────────┐ │
│ │ Hydrotest 24"-P-1203      │ │  confirmation card
│ │ PIP-A3-1203-HT · Area 3   │ │
│ │ Start: today 09:00        │ │
│ │ [ Confirm ]  [ Change ]   │ │
│ └───────────────────────────┘ │
├───────────────────────────────┤
│ [ type a message…     ] (🎤)  │
└───────────────────────────────┘
```
- The mic button shows a listening state. The interim transcript appears in the input so the user can edit before sending.
- Disambiguation shows max 3 chips with name + area + planned date.

### Review card (desktop)
```
┌───────────────────────────────────────────────────────────────────────────┐
│ DPR Piping · 14 Sep · line 7: "spool 3,4 of L-1207 erected, 2 pending"    │
│ Event: progress (finer than plan) · qty 2 spools                          │
│  1. ███████▒▒ 0.71 PIP-A3-1207-ERC  Erect line 24"-P-1207  tag ✓ area ✓   │
│  2. ███▒▒▒▒▒▒ 0.34 PIP-A3-1207-HT   Hydrotest 24"-P-1207   tag ✓ verb ✗   │
│ [A] Approve #1   [2] Pick #2   [N] New activity   [R] Reject              │
└───────────────────────────────────────────────────────────────────────────┘
```

## 5. Accessibility & usability basics (not optional)

- All actions are keyboard reachable. Visible focus. Shortcuts are documented on screen.
- Confidence is shown as number + bar + text label, never colour alone.
- Touch targets ≥ 44 px on the agent screen. Works at 360 px width.
- `aria-live="polite"` for the agent replies and processing timeline.
- Voice is always optional. Every voice action has a text equivalent.
- Contrast ≥ WCAG AA in light and dark.

## 6. State & real-time

- Server is the source of truth. Pages refetch on SSE events relevant to them (`event_applied` → schedule row refresh, `review_added` → queue badge).
- No global state library. Context holds only auth/user/project.

## 7. Build & serve

`npm run build` → `web/dist` → FastAPI mounts it as static at `/` with SPA fallback. One origin, so no CORS in the hackathon. Dev uses the Vite proxy to `localhost:8000/api`.

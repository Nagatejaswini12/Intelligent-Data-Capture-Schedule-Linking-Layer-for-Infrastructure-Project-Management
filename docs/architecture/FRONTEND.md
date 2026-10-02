# Frontend Architecture

[← Master plan](../PROJECT_MASTER_PLAN.md) · Related: [Backend API](BACKEND_API.md) · [End-to-end workflow](../plan/END_TO_END_WORKFLOW.md)

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

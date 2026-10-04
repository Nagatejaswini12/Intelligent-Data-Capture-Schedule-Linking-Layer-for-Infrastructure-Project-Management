# Upgrade Plan: "1 in 100" (W0–W5)

[← Master plan](../PROJECT_MASTER_PLAN.md) · [Phase plan](PHASE_PLAN.md) · [Evaluator Q&A](../presentation/EVALUATOR_QA.md)

## Context
Oil India (the problem-statement owner, SIH26122) judges on **return on investment**. Gaps found in the code (2026-10-03): LangGraph installed but unused, no voice, field uploads `.txt`/`.xlsx` only, no automatic reports or alerts, and nothing showing token cost or ROI. This upgrade adds **menu-first zero-token capture, voice, an ROI/token dashboard, alerts, automatic reports, more input formats and a shadow-mode pilot**, without leaving the problem statement.

**6 phases, 27 tasks. Status 2026-10-04: all phases delivered** (one decision open, two tasks found already done by the team, one deliberately kept as is). Tests: `tests/test_upgrade_w1.py` … `test_upgrade_w5.py`.

| Phase | Theme | Status |
|---|---|---|
| W0 | Sync & presentation notes | done (LangGraph removal waits for a team decision) |
| W1 | Capture: menu-first, voice, Hinglish, undo | done |
| W2 | Efficiency & ROI proof | done |
| W3 | PM reports & question menu | done |
| W4 | P6 XER, .docx / .csv uploads | done (roll-up already existed) |
| W5 | Shadow mode, blind-set evaluation, demo | done (injection + CSV tests already existed) |

## Measured on the synthetic project (as of 2026-09-16, live run)
84 reports · 433 reported items · **261 linked automatically (60.3%), 0 AI tokens** · 128 to planner review · 44 flagged as new/unknown · median **5.3 s** from upload to schedule update (vs ~3 days manual, assumption) · planner time saved **21.8 h ≈ ₹16,312** (assumptions: 5 min/item, ₹750/h) · AI cost per 1,000 reports **₹0 vs ≈ ₹1,933** if an LLM read every item (assumption: 1,500 tokens/item, ₹0.25 per 1k tokens). Rupee figures are estimates from editable assumptions on the ROI page.

---

## W0: Sync & presentation notes
1. Teammate's update (`origin/main` 478c7c9) fast-forwarded. **Found and fixed a CRLF bug:** the DPR parser rejected Windows line endings (`core.autocrlf=true` checkouts and Notepad uploads); one shared `text_lines()` now drives parsing, evidence offsets and evidence display.
2. [`docs/presentation/EVALUATOR_QA.md`](../presentation/EVALUATOR_QA.md) written.
3. *Open:* remove the unused `langgraph` from `requirements.txt`? The team docs list it as a technology choice, so the team decides.

## W1: Capture (Agent page)
- **"My activities today" menu**: reuses `GET …/watch/checklist`; a tap sends "`<plan name>` started|completed|on hold today" through the normal rules interpreter and linker, so every safety gate still applies (a tap that contradicts an earlier reported start goes to review). Test: every checklist item across disciplines, **0 wrong links**, ≥ 90% automatic.
- **Voice**: 🎤 speech-to-text and "Speak replies" (browser Web Speech API, en-IN, which writes spoken Hinglish in Latin script). Devanagari/Assamese script needs a transliteration layer and is not built.
- **Hinglish dates** "aaj"/"kal" (status verbs were already in the glossary).
- **Undo**: `POST …/agent/events/{id}/retract` sends a supervisor's own Time Agent report back to planner review (evidence kept); typing "undo" or the Undo button calls it.
- **Session memory**: "it" / "that one" are replaced by the last recorded activity, and the expanded message is what's sent and shown.

## W2: Efficiency & ROI
- `p2e/analytics/efficiency.py` + `GET …/analytics/efficiency`: decision tiers (automatic / planner / review / flagged, derived from existing link records, with no new bookkeeping), auto-link rate, LLM calls, median processing time, planner hours and ₹ saved, tokens and ₹ per 1,000 reports vs "LLM for everything", shadow-mode figures. Assumptions are validated query parameters.
- **ROI & Efficiency page**: KPI tiles, tier and evidence bars, editable assumptions, shadow-mode card, alerts table (expected work with no report, reusing the silent-activity watch).

## W3: Reports & Q&A
- `p2e/analytics/report.py` + `GET …/reports/pm?period=daily|weekly`: printable self-contained HTML (started, finished, delays and causes with evidence, silent and late activities, KPIs); all field text HTML-escaped. "Save as PDF" in the browser gives the PDF.
- `scripts/phase8/generate_reports.py` writes to `exports/reports/` (for Windows Task Scheduler).
- Analytics page: **Daily / Weekly PM report** buttons. Memory page: answers are labelled "fixed query · 0 AI tokens" (the suggested-question menu already existed).

## W4: Inputs
- **Primavera P6 XER import** (`parse_xer` in `p2e/plan/importers.py`): PROJWBS hierarchy, TASK, TASKPRED (lag hours / 8), discipline / area / activity type from P6 activity codes. Round trip of the full synthetic schedule (317 activities) matches the CSV field for field. `init_database.py --schedule file.xer`.
- **`.docx` and `.csv` field reports** (`p2e/extract/formats.py`): converted at one boundary (docx → text for the DPR parser, csv → workbook for the sheet extractor); the original is stored and hashed; zip-bomb and macro checks reused. Tests: docx = same events as the txt; csv = same events as the xlsx; evidence found in source via the API.
- **Schema note:** `.docx` / `.xer` widen the `source_document.format` CHECK; SQLite can't alter it in place, so an older `data/p2e.db` asks for `init_database.py --rebuild` (synthetic data only).
- Partial-progress roll-up: **already in the Phase 5 apply engine** (quantities → percent complete, max per source, capped at 99%; earliest start). Auto-finish at 100% quantity deliberately not added: finish needs an explicit completion report, which keeps the "every applied date matches truth" result.

## W5: Hardening & proof
- Prompt-injection and CSV formula-injection tests: **already delivered by the team** (`tests/test_phase7_hardening.py`).
- **Shadow mode**: `project.shadow_mode` (additive column), `PUT …/shadow-mode` (planner only). The automatic applier only proposes (dry run) while planner approvals still write. ROI page shows "would update N activities".
- **Blind-set evaluation** `scripts/phase8/evaluate_blind.py`: outside-written reports + `labels.csv` (`file,activity_code,event_type,event_date`; `NEW` for unplanned work) → wrong automatic links, automatic precision/coverage, review outcomes, extraction recall, on a temporary database.
- **Demo Flow step 11 "Prove the return"**: link to the ROI page + weekly report download.

---

# Languages, assistant and help (L1–L4), 2026-10-04

| Phase | What | Status |
|---|---|---|
| L1 | Tamil + Hindi understanding in the Time Agent; replies in the user's language | done |
| L2 | Interface in English / தமிழ் / हिन्दी (language picker, remembered) | done for shell, all page titles, Time Agent, ROI, Analytics, Memory, Overview, Help, assistant; detailed planner tables (Linking / Schedule / Audit columns) still English |
| L3 | Scoped multilingual assistant (chat + voice): app / project / Oil India only, with sources; everything else declined | done |
| L4 | User Guide, Terms of Use (draft), Video Guide slot + NotebookLM prompt | done; video waits for the NotebookLM export |

- **L1** (`p2e/agent/time_agent.py`, `p2e/i18n.py`): Tanglish ("inniku start panniten", "nethu mudinjidhu"), Tamil script ("இன்று தொடங்கியது", "நேற்று முடிந்தது", "நிறுத்தப்பட்டது", "மீண்டும் தொடங்கியது") and Hindi script ("आज शुरू हुआ", "कल पूरा हो गया"). Python's `\b` fails on Indic vowel signs, so explicit boundaries are used. Agent questions and replies come from one en/ta/hi catalog; the language is the request's `lang` or the message's script. English text is unchanged.
- **L2** (`web/src/i18n.ts`): key → [en, ta, hi] dictionary, `useT()` hook, picker in the top bar and on sign-in, `<html lang>` set; Time Agent menu taps send Tamil / Hindi phrases in those languages; speech recognition and spoken replies use ta-IN / hi-IN / en-IN. A test keeps every key complete in all three languages.
- **L3** (`p2e/assistant.py`, `POST …/assistant/ask`, floating **Ask P2E** on every screen): language from script or choice → topic: project (existing cited Q&A; Tamil/Hindi question words mapped to intents; the answer rebuilt in Tamil/Hindi from the computed values), app (user guide), company (`data/company/oil_india.json`: 9 Oil India facts with public source links and as-of dates, all three languages: overview, NRL, FY25 results, FY25 production, net zero 2040/ESG, renewables, CSR, market, Glassdoor reviews), greeting, otherwise a polite refusal. Deterministic, 0 tokens. Tests cover 11 in-scope and 6 out-of-scope questions across the three languages.
- **L4** (`data/help/guide.json`, `data/help/terms.json`, public `GET /api/v1/help/{guide|terms}`, pages User Guide / Terms of Use / Video Guide under **Help**): the same guide text feeds the assistant. Terms are a **draft for the operator's legal team**. Video: put the NotebookLM export at `web/public/guide-video.mp4` and rebuild; prompt in [`docs/presentation/NOTEBOOKLM_VIDEO_PROMPT.md`](../presentation/NOTEBOOKLM_VIDEO_PROMPT.md).
- **Review before production:** Tamil and Hindi wording (native speakers), company figures (they date: market data especially), terms (legal). Voice depends on the browser (Chrome / Edge) and on the device having Tamil / Hindi voices installed for spoken replies.

## Known environment note (not a code issue)
On a Windows checkout with `core.autocrlf=true`, `scripts/phase0/validate_dataset.py` reports "not byte-identical" (24/26), because Git rewrote the data files with CRLF; with `\r` removed they match the repository exactly. Fix for everyone: add a `.gitattributes` with `data/synthetic/** -text` (keeps bytes exact) and re-checkout the data folder.

## Not doing
Multi-agent orchestration, cloud LLM calls, OCR/PDF parsing, P6 API write-back, Decisions API / Jev integration (pitch slide only).

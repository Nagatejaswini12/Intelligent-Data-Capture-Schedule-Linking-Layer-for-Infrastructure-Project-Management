# Problem Analysis & Scope

[← Master plan](../PROJECT_MASTER_PLAN.md)

## 1. The statement as issued (SIH26122, Oil India Limited)

**Background.** Schedules cascade from L1 milestones to executable L5/L6 activities across civil, piping, static/rotating equipment, electrical, instrumentation and HSE. The baseline lives in Primavera/MS Project. Actuals flow back through daily progress reports (DPRs), site diaries, discipline spreadsheets and verbal updates, disconnected from L5/L6 activity IDs.

**Problem.** There is no low-friction way to capture actual start/end of L5/L6 activities and auto-link them to the plan. Input quality varies. Field execution is often *more granular* than the WBS, and disciplines describe the same progress differently. Result: fragmented, late data. Reconciliation lags by days or weeks. Downstream analytics inherit poor data. Project knowledge is lost at closure.

**Expected outcome.**
1. Ingest heterogeneous inputs (free text, spreadsheets, scanned diaries, P6/MSP exports) and extract activity-level actual start/end events.
2. An LLM conversational/voice **time agent** for supervisors that replaces rigid forms but still yields structured output.
3. Fuzzy-match to the correct L5/L6 node, handle terminology and granularity, and **flag unmatched/new activities for planner review**.
4. Auto-update actual dates in the schedule/PMIS near real time with **confidence score and audit trail**.
5. A clean, discipline-tagged dataset for (a) analytics and forecasting and (b) **institutional memory**.

**Prototype expectation.** 2–3 varied input formats, extraction, and schedule linking. Full OCR/ASR not required. Only synthetic or sample data.

## 2. What it is really asking

| Surface ask | Underlying need | Implication for design |
|---|---|---|
| "Ingest formats" | Remove the manual re-typing step | Ingestion must be forgiving (bad headers, mixed date formats, Hinglish) |
| "Time agent" | Capture at the source with near-zero friction | Mobile-first, voice-capable, 1–3 turns, works with vague references ("the pump foundation I started yesterday") |
| "Fuzzy match" | The real hard problem: **entity resolution** between field language and plan language | Hybrid linker. Tag/line/equipment numbers are the strongest signal |
| "Confidence + audit" | Planners must *trust* auto-updates | Calibrated confidence, human-in-the-loop, evidence per entry, reversible |
| "Flag unmatched" | Missing scope and plan gaps are valuable signals | Unmatched is a first-class output, not an error |
| "Institutional memory" | Learn from closed projects | Structured, queryable store and a portable knowledge export |

## 3. Domain primer (for the team)

| Term | Meaning |
|---|---|
| WBS | Work Breakdown Structure: hierarchy of the project scope |
| L1–L6 | Schedule levels. L1 = project milestones … L5/L6 = executable activities (e.g. "Erect piping Line 24"-P-1203, Area 3") |
| Activity ID | Unique ID in P6/MSP (e.g. `PIP-A3-1203-ERC`) |
| Actual Start (AS) / Actual Finish (AF) | The dates this system must capture |
| DPR | Daily Progress Report written by site supervisors/contractors |
| Spool | Prefabricated piping section. A line is erected spool by spool, which is a classic granularity mismatch |
| Tag number | Equipment/instrument identifier (e.g. `P-101A` pump, `FT-2031` flow transmitter, `24"-P-1203-A1A` line) |
| XER | Primavera P6 native export (tab-delimited tables) |
| MSPDI | MS Project XML interchange format |
| PMIS | Project Management Information System |

## 4. Users

| User | Goal | Primary surface |
|---|---|---|
| Site supervisor (each discipline) | Report what started/finished with minimal effort, often on a phone, sometimes in Hindi/Assamese/English mix | Time agent (chat/voice), DPR upload |
| Discipline engineer / contractor clerk | Submit daily spreadsheet | Upload page |
| Planner / scheduler | Keep schedule actuals correct, resolve ambiguities, spot new scope | Review queue, schedule view |
| Project manager | See real progress and delays | Dashboard |
| Future project planner | Learn real durations and delay causes | Institutional memory Q&A |

## 5. Scope

### In scope (hackathon)
- Schedule import: CSV and MS Project XML (MSPDI). P6 XER is stretch (simple text parser).
- Inputs: free-text DPR (paste/upload .txt/.docx-as-text), discipline spreadsheet (.xlsx/.csv), time agent (text + browser voice).
- Extraction to progress events. Hybrid linking with confidence. Review queue. Auto-apply. Audit trail. Live schedule view. Export of updated actuals.
- Alias memory (learning from planner confirmations).
- Analytics basics and an institutional-memory Q&A (should-have).
- Evaluation harness with metrics on labelled synthetic data.

### Stretch
- Scanned diary via OCR or vision LLM. P6 XER import. Multilingual voice (Hindi). OKF knowledge export. Delay-cause extraction.

### Out of scope (stated, so judges see it is deliberate)
- Live P6 EPPM / MS Project Online API write-back (we export files; the API connector is future scope).
- Production-grade OCR/ASR (the PS explicitly says not required).
- Cost/earned-value management, resource loading, scheduling engine (CPM recalculation stays in P6/MSP).
- Real OIL data (not available; synthetic only).

## 6. Assumptions

1. The plan export has activity ID, name, WBS path, discipline (or derivable from WBS/code), area/unit, planned start/finish, and optionally quantity and unit.
2. DPRs mention date, discipline/contractor, area, and work items in free text, often with tag/line numbers.
3. Planners accept a review step for uncertain links. Fully automatic linking is not expected to be 100%.
4. Hackathon runtime: one laptop/VM, CPU. The LLM is accessed via a Hugging Face endpoint or a local open-weight model.

## 7. Open questions to confirm with OIL (if mentors are reachable)

| Question | Default if unanswered |
|---|---|
| Which export do they use: XER or MSPDI? | Support MSPDI + CSV. XER as stretch |
| Is there a standard DPR template per discipline? | Synthetic templates modelled on common EPC DPRs |
| Can actuals be written directly to P6, or via planner import? | Export file for planner import |
| Language mix of supervisors? | English + Hinglish in the eval set. Hindi voice stretch |
| Confidence threshold preference (automation vs review load)? | Auto-apply at a threshold calibrated to ≥95% precision |

# Presentation Q&A: P2E Bridge (SIH26122)

[← Master plan](../PROJECT_MASTER_PLAN.md) · [Upgrade plan](../plan/UPGRADE_PLAN.md)

For slides, the viva and judge questions. Numbers are from the synthetic project `CGS-EXP-01` (as of 2026-09-16), measured on 2026-10-04.

## 1. One-liner
**P2E Bridge turns messy field reports into trusted, audited schedule actuals and long-term project memory, on-premise, with every routine decision costing zero AI tokens.**

## 2. Capability answers (verified in the code)

| Question | Answer |
|---|---|
| Multi-agent with LangGraph? | No, deliberately. One Time Agent (rules + optional on-premise LLM). LangGraph is installed but unused; multi-agent orchestration has no job here and would add cost and risk. |
| Multiple languages? | **English, Tamil, Hindi** across the interface (language picker), the Time Agent (Tamil script, Tanglish, Hindi script, Hinglish) and the assistant, which answers in the user's language. Zero tokens. Assamese is roadmap. |
| Chatbot / voice? | Yes: the **Ask P2E** assistant on every screen (typed or spoken, en/ta/hi) and the Time Agent (one-tap menu, chat, 🎤, spoken replies, "undo", "that one"). The assistant answers only about the app, the project and Oil India Limited, with sources; it declines everything else. |
| Company questions? | Only from **official** Oil India sources (Annual Report 2024-25, oil-india.com): results, production, NRL, Net Zero 2040, renewables, CSR, DRIVE, ratings — each cited. Reviews, social media, live share prices and analyst targets are not official, so they are not answered. |
| Official resources? | **BHASHINI** (voice + translation, incl. Assamese), **AIKosh** models for on-premise speech, **OIL official data**; data.gov.in and API Setu next; DGH NDR / eRTMAC not applicable. See `docs/OFFICIAL_RESOURCES.md`. |
| Dashboards / reports? | Analytics dashboard, live Watch feed, **ROI & Efficiency page**, and automatic **daily/weekly PM reports** (printable HTML → PDF, also by a scheduled script). |
| Upload types? | Field reports: `.txt`, `.docx`, `.xlsx`, `.csv` (10 MB cap, zip-bomb and macro checks). Schedules: CSV, MS Project XML, **Primavera P6 XER**. OCR is roadmap (problem statement says optional). |
| Hallucination control? | Rules + scoring core (no LLM needed). LLM output must fit a strict schema and every field must appear word for word in the message, otherwise it's rejected. The tie-breaker can only pick existing candidate IDs or NONE, as advice only. Q&A uses fixed templates with citations. Every event links to its source line or cell; prompt injection is tested. |
| Is AI access restricted? | Yes. Roles supervisor / planner / admin. The LLM can never apply a date. Uncertain, conflicting or new items go to a planner. Tamper-evident audit trail and undo. On-premise LLM only by default. **"AI suggests, humans decide, everything is audited."** |
| How are decisions made? | A weighted scorer (tags, learned aliases, weighted word match, discipline/area/action) with confidence gates, date-conflict checks and an alias trust rule. 0 tokens, milliseconds, explainable. |

## 3. OpenAI Decisions API vs Jev
- Decisions API (DevDay, 29 Sep 2026, limited preview): context + a closed list of answers → one answer with confidence, about 150 ms vs about 1.6 s. Fewer output tokens, but **input context is still billed**; pricing not confirmed.
- Not adopted, for the same reasons as Jev (`docs/ai/AI_APPROACHES_EVALUATION.md`): hosted cloud (OIL NDA / data sovereignty), preview maturity, and our scorer is already faster, free, offline and explainable.
- **Pitch line:** "Decisions API and Jev prove the industry is moving to fast closed-choice decision models. We built that idea on-premise, at zero token cost, with an audit trail."

## 4. Hackathon evaluator questions

| # | Question | Answer |
|---|---|---|
| 1 | 100% on your own synthetic data, isn't that rigged? | Held-out test split, independent ground truth, **0 wrong automatic links (261/261 correct)**. And `scripts/phase8/evaluate_blind.py` scores reports written by outsiders: hand it anyone's DPRs + labels and it reports wrong links first. |
| 2 | Where's the AI, isn't this regex? | Hybrid by design: rules handle routine items at zero cost, the LLM only hard cases, on-premise. Before/after comparison: without RAG 0.705, without the glossary 0.864, full system 0.918. |
| 3 | Why not GPT for everything? | Measured: **₹0 vs ≈ ₹1,933 per 1,000 reports** (≈ 7.7 M tokens), plus delay, hallucination risk and the NDA. |
| 4 | Wrong link? | Confidence gates, conflict layer, review queue, audit, undo; the LLM can't apply anything. Even a supervisor's menu tap that contradicts an earlier report goes to review. |
| 5 | Voice? | Yes, browser speech, no cloud speech service, no cost. |
| 6 | Scanned diaries? | OCR optional per the problem statement; roadmap (local OCR). `.docx` reports are supported. |
| 7 | Primavera? | **P6 XER import** (round trip of 317 activities exact) and MS Project XML; exports for planner import. |
| 8 | Scale? | SQLite now → Postgres + pgvector, stateless replicas (FUTURE_SCOPE.md). |
| 9 | Security? | Role keys, upload limits, defusedxml, macro rejection, private LLM only, CSV formula escaping, prompt-injection tests, hash-chained audit. |
| 10 | What's new? | Zero-token menu capture, unmatched work as a signal, alias memory that has to earn trust, date-conflict layer, cited answers, ROI measured inside the product, shadow-mode pilot. |

## 5. Oil India owner questions (ROI)

| Question | Answer |
|---|---|
| What do I get back for my money? | On the demo project: **21.8 planner hours (≈ ₹16,312) saved on 433 items**, 60% linked automatically, median **5.3 s** from upload to schedule vs ~3 days manually. The ROI page recomputes this with OIL's own rates. Earlier delay visibility: "expected work with no report" alerts every day. |
| Running cost? | One CPU server; **0 AI tokens** for routine decisions; optional on-premise LLM with no per-call fees. |
| Will supervisors use it? | One tap per activity from "My activities today", or voice/chat in Hinglish; a follow-up question only when something is missing. |
| Replace P6? | No. It imports P6 XER / MS Project and exports actuals for planner import. |
| Data safety? | Runs entirely on OIL's network, no external AI calls, roles + tamper-evident audit. |
| Rollout risk? | **Shadow mode**: run beside the current process on one live project. It proposes but writes nothing automatically, the planner compares, then auto-apply is switched on per project. |
| Reuse on the next project? | Aliases, glossary and lessons carry over via the knowledge export (OKF). |

## 6. Key numbers (synthetic)
317 activities · 84 field reports · 433 reported items · extraction F1 1.0 · **261 automatic links, 0 wrong** · 128 to review · 44 flagged new/unknown · linking agreement 0.918 on held-out test data · top-3 0.963 · every applied date matches ground truth (48/48 starts, 31/31 finishes) · Q&A 10/10 with citations · 0 AI tokens · 5.3 s upload → schedule · 11 web screens.

## 7. Demo storyline (5 min)
1. Agent page → pick "piping" → **tap Start** on an activity from "My activities today" → linked and recorded (0 tokens).
2. 🎤 say "LT-4011 loop check kal complete ho gaya" → finish on yesterday's date, linked automatically.
3. Tap "started today" on an activity the DPR already reported started → **held for planner review** (conflict layer). Show "Undo".
4. Linking / review queue → planner resolves with one click → schedule updates, audit entry.
5. **ROI & Efficiency** page: 60% automatic, 0 tokens, ₹ comparison, hours saved, alerts; toggle shadow mode.
6. Analytics → **Weekly PM report** → open → "Save as PDF".
7. Memory: "Why was piping in Area 3 late?" → cited answer, "0 AI tokens".
8. Close on the ROI slide.

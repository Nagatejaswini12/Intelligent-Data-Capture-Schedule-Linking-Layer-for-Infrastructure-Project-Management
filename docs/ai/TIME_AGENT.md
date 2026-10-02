# Text Time Agent (Phase 4)

[← Master plan](../PROJECT_MASTER_PLAN.md) · Related: [Linking layer](LINKING_LAYER.md) · [Backend](../architecture/BACKEND_API.md)

**Purpose.** A site supervisor types a progress message ("Line 1203 hydrotest finished yesterday at 4 pm"); the agent turns it into one structured progress event and hands it to the existing Phase 3 linker. It never picks an activity, never writes the schedule (Phase 5) and never invents a value.

## Flow

```
POST /api/v1/projects/{code}/agent/messages {message, reference_datetime?, discipline?, answers?}
  → interpret: rules (default)  |  LLM (only if P2E_LLM_ENDPOINT is a self-hosted endpoint; JSON validated, else rules)
  → resolve dates against reference_datetime → missing/ambiguous field? → question (nothing stored)
  → Phase 2 validation (validate_item) → invalid (e.g. future date)? → "Not recorded: …" (nothing stored)
  → store the message as a text source document + one progress_event (extraction_method = time-agent)
  → existing p2e.link.service.link_events([event]) → RAG / CAG / MAG / conflict layer → MATCH | REVIEW | UNMATCHED
```

Code: `p2e/agent/time_agent.py`, `p2e/api/agent.py`. Role: any API key (supervisor, planner, admin).

## Structured event

`activity_text` (a verbatim part of the message), `event_type` (start / finish / progress, plus hold / resume from the glossary verbs), `event_date`, `actual_start` / `actual_finish` (= `event_date` for start / finish), `date_text`, `event_time`, `quantity` + `unit` (spools, m, cables, rings, cum), `discipline`, `area`, `tags`, `interpreted_by` (rules | llm), `extraction_confidence` (1.0 for the deterministic interpreter, which only copies literal text; the LLM's own value otherwise), `notes` (e.g. why LLM output was rejected), `missing`.

Rules interpreter: Phase 2 glossary event verbs, `parse_date` / `parse_time`, tag and area extractors. A number that is part of a recognised identifier ("Line 1211 spool") is never read as a quantity. LLM interpreter: output must match a strict schema (unknown keys such as an activity code are rejected) and every text field must appear in the message, quantities included; otherwise it is discarded and the rules interpreter is used.

## Date handling

`today`, `yesterday` / `yday`, explicit dates (2026-09-14, 14/09/2026, 14.09.26, 14-Sep, Sep 14, 2026) and times (4 pm, at 10:30). Relative dates resolve against `reference_datetime` (request field; default: now in the project timezone, read once per request; `tzdata` provides the zone on Windows). Several different dates, or none, → the agent asks.

## Clarification

Only for fields the event cannot be recorded without: activity (resend with the line/equipment/area), status (start/finish/progress), date, discipline (also taken from the request's `discipline`, the supervisor's own discipline). Stateless: the client resends the same message with `answers: {date, discipline}`. A vague but identifiable report ("Foundation works in Area-3") is recorded and left to the linker, which sends it to review.

## Linking result

| Linker decision | Reply |
|---|---|
| matched | "Recorded and linked to {code} ({name})." |
| review (incl. a cross-source date conflict) | "Recorded, but planner review is required." |
| unmatched | "Recorded, but it could not be safely linked to an existing activity." |

The response also carries the full link detail (candidates, reasons, conflict). No reply claims the schedule was updated.

## Audit trail

The stored document is `received: <reference datetime> | role: <role>`, then the message verbatim on line 3, then the interpretation metadata (interpreter, version, confidence, notes, answers). The event's `source_text` is the message and its span points at line 3, so `GET …/events/{id}/evidence` shows it like any other report. Re-sending the same message with the same reference time and answers returns `duplicate`. Phase 2 batch processing never re-parses an agent document (a document produced by another extractor is left unchanged).

## Limitations

Text only: no voice, speech-to-text or text-to-speech yet. One fact per message. Clarification state is kept by the client, not the server. Questions themselves are not stored (only recorded events are). The LLM interpreter is off unless an on-premise endpoint is configured.

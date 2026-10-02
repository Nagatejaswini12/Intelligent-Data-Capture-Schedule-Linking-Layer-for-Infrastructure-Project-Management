// Typed calls to the EXISTING P2E Bridge API (Phases 1-6 + the Phase 7 additions noted inline).
import { api, download, request } from "./client";

export type Decision = "matched" | "review" | "unmatched";
export type LinkState = "auto" | "pending" | "confirmed" | "rejected";

export interface Project { code: string; name: string; timezone: string; data_date: string | null }
export interface Run { id: number; extractor: string; parser_version: string; status: string; events_total: number;
  events_valid: number; events_invalid: number; issues_count: number; error: string | null; finished_at: string | null }
export interface DocumentOut { id: number; kind: string; format: string; filename: string; sha256: string; size_bytes: number;
  status: string; uploaded_by: string | null; report_date: string | null; discipline_group: string | null; error: string | null;
  created_at: string; latest_run: Run | null }
export interface Page<T> { items: T[]; total: number; limit: number; offset: number }
export interface EventOut { id: number; document_id: number; document_filename: string; source_type: string; source_ref: Record<string, unknown>;
  source_text: string; report_date: string | null; discipline: string | null; activity_text: string; event_type: string | null;
  event_date: string | null; date_text: string | null; event_time: string | null; quantity: number | null; unit: string | null;
  area: string | null; tags: string[]; delay_reason: string | null; delay_category: string | null; extraction_method: string;
  validation_status: string; validation_errors: string[] }
export interface Evidence { document_id: number; filename: string; kind: string; source_text: string; found_in_source: boolean;
  line_number?: number | null; line_text?: string | null; span_start?: number | null; span_end?: number | null;
  context?: { line: number; text: string }[] | null; sheet?: string | null; row?: number | null;
  cells?: { header: string; cell: string; value: unknown; value_in_file: unknown; matches: boolean }[] | null }
export interface Candidate { rank: number; plan_node_code: string; activity_name: string; level: number; discipline: string | null;
  area: string | null; score: number; retrieval_methods: string[]; matched_tags: string[]; matched_terms: string[];
  features: Record<string, unknown>; reasons: string[] }
export interface ConflictEvent { event_id: number; document_id: number; document: string; source_type: string; event_type: string | null;
  event_date: string | null; quantity: number | null; unit: string | null; source_text: string }
export interface Conflict { type: string; plan_node_code: string; dates: string[]; findings: { rule: string; detail: string }[];
  events: ConflictEvent[] }
export interface LinkOut { event_id: number; document_id: number; activity_text: string; event_type: string | null; event_date: string | null;
  decision: Decision; state: LinkState; plan_node_code: string | null; confidence: number; margin: number; unmatched_type: string | null;
  method: string; retrieval_used: boolean; reasons: string[]; llm_suggestion: Record<string, unknown> | null;
  decided_by: string | null; decided_at: string | null; conflict: Conflict | null }
export interface LinkDetail extends LinkOut { source_text: string; source_ref: Record<string, unknown>; candidates: Candidate[] }
export interface Proposal { plan_node_code: string; activity_name: string; proposed: Record<string, unknown>;
  changes: Record<string, [unknown, unknown]>; evidence_event_ids: number[]; confidence: number | null; basis: string;
  blockers: string[]; warnings: string[] }
export interface ReviewQueue { as_of: string; counts: Record<string, number>; events: LinkDetail[]; activities: Proposal[] }
export interface AuditEntry { id: number; plan_node_code: string; action: string; changes: Record<string, [unknown, unknown]>;
  actor: string; rule: string; confidence: number | null; evidence_event_ids: number[]; warnings: string[];
  reverts_id: number | null; undone_by: number | null; created_at: string }
export interface ApplyOut { as_of: string; dry_run: boolean; applied: AuditEntry[]; would_apply: Proposal[]; blocked: Proposal[]; unchanged: number }
export interface WatchItem { plan_node_code: string; activity_name: string; discipline: string | null; area: string | null;
  planned_start: string; planned_finish: string; actual_start: string | null; expectation: string; last_reported: string | null;
  days_silent?: number | null; reported_today?: boolean | null }
export interface WatchOut { as_of: string; days: number | null; counts: Record<string, number>; items: WatchItem[] }
export interface DisciplineStats { activities: number; completed?: number; in_progress?: number; not_started?: number;
  started_late?: number; finished_late?: number; due_not_started?: number }
export interface Dashboard { as_of: string; by_discipline: Record<string, DisciplineStats>; by_area: Record<string, DisciplineStats>;
  freshness: Record<string, { last_report: string; days_since: number }>; silent_activities_by_discipline: Record<string, number>;
  review_backlog: { pending_events: number; pending_conflicts: number; blocked_activities: number } }
export interface DatasetRow { code: string; name: string; discipline: string | null; area: string | null; activity_type: string | null;
  level: number; planned_start: string; planned_finish: string; planned_duration_days: number; actual_start: string | null;
  actual_finish: string | null; actual_duration_days: number | null; duration_ratio: number | null; start_variance_days: number | null;
  finish_variance_days: number | null; status: "completed" | "in_progress" | "not_started"; percent_complete: number | null;
  planned_qty: number | null; qty_unit: string | null; reported_qty: number | null; reports: number; sources: number;
  last_reported: string | null; delay_categories: string }
export interface TreeNode { code: string; node_type: string; level: number; name: string; discipline: string | null; area: string | null;
  planned_start: string; planned_finish: string; child_count: number; children: TreeNode[] }
export interface Productivity { as_of: string; durations: Record<string, { completed: number; mean_actual_days: number;
  mean_planned_days: number; mean_ratio: number; activities: string[] }>; rates: Record<string, Record<string, { quantity: number; days: number; per_day: number }>> }
export interface DelayReport { event_id: number; date: string; discipline: string | null; activity: string | null; category: string;
  reason: string; source_text: string }
export interface Delays { as_of: string; by_category: Record<string, number>; by_discipline: Record<string, Record<string, number>>;
  by_area: Record<string, Record<string, number>>; recurring: { discipline: string; category: string; reports: number }[]; reports: DelayReport[] }
export interface Citation { kind: "activity" | "event" | "document"; id: string | number; text: string; date?: string; activity?: string | null }
export interface Answer { question: string; intent: string; filters: Record<string, unknown>; answer: string; values: Record<string, unknown>;
  citations: Citation[] }
export interface KnowledgeEntry { id: string; kind: string; title: string; text: string; values: Record<string, unknown>; citations: Citation[] }
export interface AgentReply { status: "recorded" | "duplicate" | "needs_clarification" | "rejected" | "checklist"; reply: string;
  question: string | null; interpretation: Record<string, unknown>; event_id: number | null; document_id: number | null;
  reference_datetime: string; link: LinkDetail | null; checklist: (WatchItem & { reported_today: boolean })[] | null }

const P = (code: string) => `/api/v1/projects/${encodeURIComponent(code)}`;

/** Every backend route the UI uses (checked by the backend contract test tests/test_phase7.py). */
export const p2e = {
  health: () => api<{ status: string; version: string }>("/health"),
  projects: () => api<Project[]>("/api/v1/projects"),
  // Phase 2: documents, events, evidence
  documents: (c: string, q: { kind?: string; status?: string; limit?: number } = {}) => api<Page<DocumentOut>>(`${P(c)}/documents`, { query: q }),
  documentStatus: (c: string, id: number) => api<{ status: string; runs: number; latest_run: Run | null; issues: { message: string; source_text: string }[] }>(`${P(c)}/documents/${id}/status`),
  upload: (c: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api<DocumentOut>(`${P(c)}/documents`, { method: "POST", form });
  },
  process: (c: string, id: number) => api<{ outcome: string; run: Run }>(`${P(c)}/documents/${id}/process`, { method: "POST" }),
  processAll: (c: string) => api<{ counts: Record<string, number> }>(`${P(c)}/documents/process`, { method: "POST" }),
  events: (c: string, q: Record<string, string | number | undefined>) => api<Page<EventOut>>(`${P(c)}/events`, { query: q }),
  event: (c: string, eventId: number) => api<EventOut>(`${P(c)}/events/${eventId}`),
  evidence: (c: string, eventId: number) => api<Evidence>(`${P(c)}/events/${eventId}/evidence`),
  // Phase 3: linking
  runLinker: (c: string) => api<{ counts: Record<string, number>; conflicts: Record<string, number> }>(`${P(c)}/links/run`, { method: "POST" }),
  links: (c: string, q: Record<string, string | number | boolean | undefined>) => api<Page<LinkOut>>(`${P(c)}/links`, { query: q }),
  link: (c: string, eventId: number) => api<LinkDetail>(`${P(c)}/links/${eventId}`),
  reject: (c: string, eventId: number) => api<LinkDetail>(`${P(c)}/links/${eventId}/reject`, { method: "POST" }),
  hold: (c: string, eventId: number) => api<LinkDetail>(`${P(c)}/links/${eventId}/hold`, { method: "POST" }),   // Phase 7
  // Phase 5: review, apply, audit, export
  review: (c: string, asOf: string) => api<ReviewQueue>(`${P(c)}/review`, { query: { as_of: asOf, limit: 200 } }),
  approve: (c: string, eventId: number, asOf: string, code?: string) =>
    api<{ link: LinkDetail; learned: unknown[]; apply: ApplyOut }>(`${P(c)}/review/events/${eventId}/approve`, { method: "POST", body: { plan_node_code: code, as_of: asOf } }),
  newActivity: (c: string, eventId: number, body: { parent_code: string; code: string; name: string; as_of: string }) =>
    api<{ link: LinkDetail; apply: ApplyOut }>(`${P(c)}/review/events/${eventId}/new-activity`, { method: "POST", body }),
  override: (c: string, code: string, body: Record<string, unknown>) => api<AuditEntry>(`${P(c)}/review/activities/${encodeURIComponent(code)}/override`, { method: "POST", body }),
  apply: (c: string, asOf: string, dryRun: boolean) => api<ApplyOut>(`${P(c)}/apply`, { method: "POST", body: { as_of: asOf, dry_run: dryRun } }),
  audit: (c: string, q: Record<string, string | number | undefined>) => api<Page<AuditEntry>>(`${P(c)}/audit`, { query: q }),
  undo: (c: string, id: number) => api<AuditEntry>(`${P(c)}/audit/${id}/undo`, { method: "POST" }),
  exportCsv: (c: string) => download(`${P(c)}/export/schedule.csv`, `${c}-actuals.csv`),
  exportXml: (c: string, asOf: string) => download(`${P(c)}/export/schedule.xml`, `${c}-actuals.xml`, { status_date: asOf }),
  stream: (c: string, signal: AbortSignal) => request(`${P(c)}/stream`, { signal }),
  // Phase 1: schedule tree
  hierarchy: (c: string) => api<TreeNode>(`${P(c)}/hierarchy`),
  // Phase 4: Time Agent
  agent: (c: string, body: { message: string; reference_datetime: string; discipline?: string; answers?: Record<string, string> }) =>
    api<AgentReply>(`${P(c)}/agent/messages`, { method: "POST", body }),
  // Silent-activity watch
  silent: (c: string, q: { as_of: string; days?: number; discipline?: string; area?: string }) => api<WatchOut>(`${P(c)}/watch/silent`, { query: q }),
  checklist: (c: string, q: { as_of: string; discipline: string; area?: string }) => api<WatchOut>(`${P(c)}/watch/checklist`, { query: q }),
  // Phase 6: analytics + memory
  dashboard: (c: string, asOf: string) => api<Dashboard>(`${P(c)}/analytics/dashboard`, { query: { as_of: asOf } }),
  dataset: (c: string, asOf: string) => api<{ as_of: string; items: DatasetRow[] }>(`${P(c)}/analytics/dataset`, { query: { as_of: asOf } }),   // Phase 7
  productivity: (c: string, asOf: string) => api<Productivity>(`${P(c)}/analytics/productivity`, { query: { as_of: asOf } }),
  delays: (c: string, asOf: string) => api<Delays>(`${P(c)}/analytics/delays`, { query: { as_of: asOf } }),
  knowledge: (c: string, asOf: string) => api<KnowledgeEntry[]>(`${P(c)}/knowledge`, { query: { as_of: asOf } }),
  ask: (c: string, question: string, asOf: string) => api<Answer>(`${P(c)}/memory/ask`, { method: "POST", body: { question, as_of: asOf } }),
};

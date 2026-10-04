import type { ReactElement } from "react";
import { renderToString as ssr } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AgentReply, Answer, Dashboard, LinkDetail } from "../api/p2e";
import { ReplyCard } from "../pages/Agent";
import { AnswerCard } from "../pages/Memory";
import { OverviewPage } from "../pages/Overview";
import { AppContext } from "../state";
import agentClarify from "../test/fixtures/agentClarify.json";
import agentMatched from "../test/fixtures/agentMatched.json";
import answerDelays from "../test/fixtures/answerDelays.json";
import dashboard from "../test/fixtures/dashboard.json";
import linkConflict from "../test/fixtures/linkConflict.json";
import { Bars, CompareBars, ErrorBox, Flow, Kpi, StackBars } from "./ui";

/** Server-render to HTML without React's text-boundary comments. */
const renderToString = (el: ReactElement) => ssr(el).replace(/<!-- -->/g, "");

// Fixtures are real API responses captured from the synthetic project (see docs/architecture/FRONTEND.md).

describe("components render real backend shapes", () => {
  it("Time Agent reply: structured interpretation + matched activity", () => {
    const html = renderToString(<ReplyCard reply={agentMatched as unknown as AgentReply} onAnswer={() => undefined} busy={false} />);
    expect(html).toContain("INS-A4-LT4011-LCK");
    expect(html).toContain("2026-09-15");
    expect(html).toContain("16:00");
    expect(html).toContain("Matched");
  });

  it("Time Agent clarification shows the question and an answer box", () => {
    const html = renderToString(<ReplyCard reply={agentClarify as unknown as AgentReply} onAnswer={() => undefined} busy={false} />);
    expect(html).toContain("What date was it completed?");
    expect(html).toContain("today, yesterday or 2026-09-14");
  });

  it("memory answer lists its citations", () => {
    const a = answerDelays as unknown as Answer;
    const html = renderToString(<AnswerCard q={a.question} a={a} />);
    expect(html).toContain(a.answer.slice(0, 20));
    expect(html).toContain(`${a.citations.length} citations`);
    expect(html).toContain(String(a.citations[0].id));
  });

  it("charts render only the given counts", () => {
    const d = dashboard as unknown as Dashboard;
    const rows = Object.entries(d.by_discipline).map(([k, v]) => [k, v as unknown as Record<string, number>] as [string, Record<string, number>]);
    expect(renderToString(<StackBars rows={rows} segments={[{ key: "completed", label: "Completed", tone: "ok" }]} />)).toContain("Piping");
    expect(renderToString(<Bars data={[["material", 2]]} />)).toContain(">2<");
    expect(renderToString(<Bars data={[]} />)).toContain("No data");
    expect(renderToString(<CompareBars rows={[["civil", 3, 5]]} a={{ label: "Planned", tone: "muted" }} b={{ label: "Actual", tone: "ok" }} />)).toContain("3 / 5");
  });

  it("flow, KPI and error states", () => {
    const link = linkConflict as unknown as LinkDetail;
    expect(link.conflict?.type).toBe("cross_source_date_conflict");
    expect(renderToString(<Flow steps={[{ label: "Field report", value: link.source_text }]} />)).toContain("Field report");
    expect(renderToString(<Kpi label="Needs planner review" value={7} />)).toContain("Needs planner review");
    expect(renderToString(<ErrorBox error="Backend unavailable" />)).toContain("Backend unavailable");
  });

  it("a page starts in a loading state (no placeholder numbers)", () => {
    const html = renderToString(
      <AppContext.Provider value={{ project: { code: "CGS-EXP-01", name: "x", timezone: "Asia/Kolkata", data_date: null }, asOf: "2026-09-16", setAsOf: () => undefined, live: "", snapshot: null }}>
        <OverviewPage />
      </AppContext.Provider>,
    );
    expect(html).toContain("Loading project status");
    expect(html).not.toMatch(/kpi-value/);
  });
});

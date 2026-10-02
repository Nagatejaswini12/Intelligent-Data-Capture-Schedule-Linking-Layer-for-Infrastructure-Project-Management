import { describe, expect, it } from "vitest";
import { parseSse } from "../hooks/useStream";
import { decisionTone, fmtDate, fmtNum, humanize, pct, statusTone, variance } from "./format";
import { href, parseHash } from "./route";

describe("formatting", () => {
  it("formats without inventing values", () => {
    expect(fmtDate("2026-09-16T10:00:00Z")).toBe("2026-09-16");
    expect(fmtDate(null)).toBe("—");
    expect(fmtNum(0.84567)).toBe("0.85");
    expect(fmtNum(null)).toBe("—");
    expect(pct(1, 4)).toBe("25%");
    expect(pct(1, 0)).toBe("—");
    expect(variance(3)).toBe("+3 d");
    expect(variance(0)).toBe("on time");
    expect(variance(null)).toBe("—");
    expect(humanize("in_progress")).toBe("in progress");
  });

  it("maps decisions and statuses to tones", () => {
    expect(decisionTone("matched", "auto")).toBe("ai");
    expect(decisionTone("matched", "confirmed")).toBe("ok");
    expect(decisionTone("review", "pending")).toBe("warn");
    expect(decisionTone("unmatched", "auto")).toBe("bad");
    expect(statusTone("completed")).toBe("ok");
  });
});

describe("routing and live stream", () => {
  it("parses and builds hash routes", () => {
    const r = parseHash("#/linking?event=12&decision=review");
    expect(r.page).toBe("linking");
    expect(r.params.get("event")).toBe("12");
    expect(parseHash("").page).toBe("overview");
    expect(href("schedule", { q: "PIP-A3-1211-ERC", late: undefined })).toBe("#/schedule?q=PIP-A3-1211-ERC");
  });

  it("parses server-sent events across chunk boundaries", () => {
    const a = parseSse('event: update\ndata: {"audit_last_id":1}\n\n: keep-alive\n\nevent: update\ndata: {"audit');
    expect(a.events).toEqual(['{"audit_last_id":1}']);
    const b = parseSse(a.rest + '_last_id":2}\n\n');
    expect(b.events).toEqual(['{"audit_last_id":2}']);
  });
});

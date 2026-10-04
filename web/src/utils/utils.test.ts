import { describe, expect, it } from "vitest";
import { parseSse } from "../hooks/useStream";
import { decisionTone, fmtDate, fmtNum, humanize, pct, statusTone, variance } from "./format";
import { guard } from "./localAi";
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
    expect(humanize("in_progress")).toBe("In progress");
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

import { expandReference, UNDO } from "../pages/Agent";

describe("time agent session memory", () => {
  it("replaces a pronoun with the last recorded activity, only when there is one", () => {
    expect(expandReference("it finished today", "Line 1211 hydrotest")).toBe("Line 1211 hydrotest finished today");
    expect(expandReference("that one completed yesterday", "LT-4011 loop check")).toBe("LT-4011 loop check completed yesterday");
    expect(expandReference("it finished today", null)).toBe("it finished today");
    expect(expandReference("Line 1203 hydrotest started today", "LT-4011 loop check")).toBe("Line 1203 hydrotest started today");
    expect(UNDO.test("undo last") && UNDO.test(" Undo ") && !UNDO.test("undo the pump")).toBe(true);
  });
});

import { missingTranslations, translate } from "../i18n";

describe("interface languages", () => {
  it("has English, Tamil and Hindi for every string and fills parameters", () => {
    expect(missingTranslations()).toEqual([]);
    expect(translate("ta", "nav.agent")).toBe("நேர முகவர்");
    expect(translate("hi", "roi.autoHint", { a: 261, n: 433 })).toBe("433 में से 261 आइटम");
    expect(translate("en", "overview.sub", { asOf: "2026-09-16" })).toContain("2026-09-16");
    expect(translate("ta", "no.such.key")).toBe("no.such.key");
  });
});

describe("on-device AI guard", () => {
  const prompt = [{ role: "system" as const, content: "rules" }, { role: "user" as const, content: "<facts>12 activities delayed, 3 on hold</facts> Question: how many?" }];
  it("keeps grounded answers and rejects hallucinated numbers or out-of-scope replies", () => {
    expect(guard("<think>x</think> 12 activities are delayed and 3 are on hold.", prompt)).toBe("12 activities are delayed and 3 are on hold.");
    expect(guard("15 activities are delayed.", prompt)).toBeNull();
    expect(guard("OUT_OF_SCOPE", prompt)).toBeNull();
    expect(guard("  ", prompt)).toBeNull();
    expect(guard("௧௫ தாமதம்", prompt)).toBeNull();        // Tamil digits are numbers too
    expect(guard("12 are delayed.", prompt, "12 delayed, 3 on hold")).toBeNull();   // dropped a verified number
    expect(guard("12 delayed and 3 on hold.", prompt, "12 delayed, 3 on hold")).toBe("12 delayed and 3 on hold.");
  });
});

import { useEffect, useState } from "react";
import { p2e } from "../api/p2e";

export interface Snapshot { audit_last_id: number; pending_review: number; decisions: Record<string, number>; activities_with_actuals: number }

/** Parse server-sent events out of a text buffer; returns complete `data:` payloads and the unparsed rest. */
export function parseSse(buffer: string): { events: string[]; rest: string } {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events = blocks.flatMap((b) => b.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)));
  return { events, rest };
}

/** Live project snapshot from the Phase 5 SSE stream (read with fetch because EventSource cannot send the API key). */
export function useStream(project: string | null, enabled: boolean): { snapshot: Snapshot | null; connected: boolean } {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!project || !enabled) return;
    const ctrl = new AbortController();
    let stopped = false;
    (async () => {
      while (!stopped) {
        try {
          const res = await p2e.stream(project, ctrl.signal);
          setConnected(true);
          const reader = res.body!.getReader();
          const dec = new TextDecoder();
          let buf = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            const parsed = parseSse(buf + dec.decode(value, { stream: true }));
            buf = parsed.rest;
            for (const e of parsed.events) setSnapshot(JSON.parse(e));
          }
        } catch {
          /* fall through to retry */
        }
        setConnected(false);
        if (!stopped) await new Promise((r) => setTimeout(r, 5000));
      }
    })();
    return () => {
      stopped = true;
      ctrl.abort();
    };
  }, [project, enabled]);
  return { snapshot, connected };
}

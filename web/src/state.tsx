import { createContext, useContext } from "react";
import type { Project } from "./api/p2e";
import type { Snapshot } from "./hooks/useStream";

export interface AppState {
  project: Project;
  asOf: string;                  // reporting date used by every as-of query (history before it, nothing after)
  setAsOf: (d: string) => void;
  live: string;                  // changes whenever the backend snapshot changes -> pages refetch
  snapshot: Snapshot | null;
}

export const AppContext = createContext<AppState | null>(null);

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("AppContext missing");
  return ctx;
}

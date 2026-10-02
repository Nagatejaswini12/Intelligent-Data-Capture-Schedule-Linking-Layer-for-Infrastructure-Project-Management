// Hash routing (#/page?key=value): no router dependency for ten screens.
import { useEffect, useState } from "react";

export interface Route { page: string; params: URLSearchParams }

export function parseHash(hash: string): Route {
  const [path, qs] = hash.replace(/^#\/?/, "").split("?");
  return { page: path || "overview", params: new URLSearchParams(qs ?? "") };
}

export function href(page: string, params: Record<string, string | number | undefined> = {}): string {
  const qs = Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
  return `#/${page}${qs ? `?${qs}` : ""}`;
}

export function navigate(page: string, params: Record<string, string | number | undefined> = {}) {
  window.location.hash = href(page, params);
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

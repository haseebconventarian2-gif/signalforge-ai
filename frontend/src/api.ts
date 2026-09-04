import type { AgentStatus, Analytics, Candidate, Configuration, Order, Overview, Position, ScanResult } from "./types";

const apiOrigin = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiOrigin}/api/v1${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => null);
    throw new Error(problem?.detail ?? `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function eventStreamUrl(): string {
  const configuredOrigin = (
    import.meta.env.VITE_WS_BASE_URL ?? import.meta.env.VITE_API_BASE_URL ?? ""
  ).replace(/\/$/, "");
  const url = new URL(
    "/api/v1/events",
    configuredOrigin || window.location.origin,
  );
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export const api = {
  overview: () => request<Overview>("/dashboard/overview"),
  agent: () => request<AgentStatus>("/agent/status"),
  candidates: () => request<Candidate[]>("/dashboard/candidates"),
  positions: () => request<Position[]>("/dashboard/positions"),
  orders: () => request<Order[]>("/dashboard/orders"),
  analytics: () => request<Analytics>("/dashboard/analytics"),
  configuration: () => request<Configuration>("/dashboard/configuration"),
  opportunities: () => request<ScanResult>("/market/opportunities"),
  control: (
    action: "start" | "pause" | "scan" | "kill-switch" | "kill-switch/reset",
    token: string,
  ) => request<AgentStatus>(`/agent/${action}`, {
      method: "POST",
      headers: { "X-Control-Token": token },
    }),
};

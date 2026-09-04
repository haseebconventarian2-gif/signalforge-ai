import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, eventStreamUrl } from "./api";
import type { AgentStatus, Analytics, Candidate, Configuration, Order, Overview, Position, ScanResult } from "./types";

type Data = {
  overview: Overview | null;
  agent: AgentStatus | null;
  candidates: Candidate[];
  positions: Position[];
  orders: Order[];
  analytics: Analytics | null;
  scan: ScanResult | null;
  configuration: Configuration | null;
  scanning: boolean;
  loading: boolean;
  error: string | null;
  connected: boolean;
  refresh: () => Promise<void>;
  scanMarket: () => Promise<void>;
  control: (action: "start" | "pause" | "scan" | "kill-switch" | "kill-switch/reset", token: string) => Promise<void>;
};

const DataContext = createContext<Data | null>(null);

export function DataProvider({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<Omit<Data, "refresh" | "scanMarket" | "control">>({
    overview: null,
    agent: null,
    candidates: [],
    positions: [],
    orders: [],
    analytics: null,
    scan: null,
    configuration: null,
    scanning: false,
    loading: true,
    error: null,
    connected: false,
  });
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [overview, agent, candidates, positions, orders, analytics, configuration] = await Promise.all([
        api.overview(), api.agent(), api.candidates(), api.positions(), api.orders(), api.analytics(), api.configuration(),
      ]);
      if (mounted.current) setData((value) => ({ ...value, overview, agent, candidates, positions, orders, analytics, configuration, loading: false, error: null }));
    } catch (error) {
      if (mounted.current) setData((value) => ({ ...value, loading: false, error: error instanceof Error ? error.message : "Unknown API error" }));
    }
  }, []);

  const control = useCallback(async (action: "start" | "pause" | "scan" | "kill-switch" | "kill-switch/reset", token: string) => {
    await api.control(action, token);
    await refresh();
  }, [refresh]);

  const scanMarket = useCallback(async () => {
    if (mounted.current) setData((value) => ({ ...value, scanning: true }));
    try {
      const scan = await api.opportunities();
      if (mounted.current) setData((value) => ({ ...value, scan, error: null }));
    } catch (error) {
      if (mounted.current) setData((value) => ({ ...value, error: error instanceof Error ? error.message : "Market scan failed" }));
    } finally {
      if (mounted.current) setData((value) => ({ ...value, scanning: false }));
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    let socket: WebSocket | null = null;
    let timer: number | null = null;
    const connect = () => {
      socket = new WebSocket(eventStreamUrl());
      socket.onopen = () => setData((value) => ({ ...value, connected: true }));
      socket.onmessage = (event) => { if (JSON.parse(event.data).type !== "heartbeat") void refresh(); };
      socket.onclose = () => {
        setData((value) => ({ ...value, connected: false }));
        timer = window.setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      mounted.current = false;
      if (timer) window.clearTimeout(timer);
      socket?.close();
    };
  }, [refresh]);

  return <DataContext.Provider value={{ ...data, refresh, scanMarket, control }}>{children}</DataContext.Provider>;
}

export function useData(): Data {
  const value = useContext(DataContext);
  if (!value) throw new Error("useData must be used within DataProvider");
  return value;
}

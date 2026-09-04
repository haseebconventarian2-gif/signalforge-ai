import { AlertTriangle, CheckCircle2, LoaderCircle, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

export function PageHeader({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) {
  return <header className="page-header"><div><h1>{title}</h1><p>{detail}</p></div>{action}</header>;
}

export function StatusBadge({ value }: { value: string }) {
  const tone = /APPROVED|RUNNING|FILLED|OPEN|BUY/.test(value) ? "positive" : /REJECT|ERROR|KILL|CANCEL/.test(value) ? "negative" : "neutral";
  return <span className={`badge ${tone}`}>{value.replaceAll("_", " ")}</span>;
}

export function Money({ value, signed = false }: { value: string | number | null; signed?: boolean }) {
  const number = Number(value ?? 0);
  return <span className={signed ? number >= 0 ? "gain" : "loss" : ""}>{new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2, signDisplay: signed ? "exceptZero" : "auto" }).format(number)}</span>;
}

export function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="empty"><CheckCircle2 size={24} /><strong>{title}</strong><span>{detail}</span></div>;
}

export function Loading() {
  return <div className="loading"><LoaderCircle className="spin" size={22} />Loading current system state</div>;
}

export function ErrorState({ message, retry }: { message: string; retry: () => void }) {
  return <div className="error-state"><AlertTriangle size={24} /><strong>Backend unavailable</strong><span>{message}</span><button className="button secondary" onClick={retry}><RefreshCw size={16} />Retry</button></div>;
}

export function Metric({ label, children, detail }: { label: string; children: ReactNode; detail?: string }) {
  return <div className="metric"><span>{label}</span><strong>{children}</strong>{detail && <small>{detail}</small>}</div>;
}

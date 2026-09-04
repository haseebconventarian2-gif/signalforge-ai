import {
  Activity, Bot, BrainCircuit, BriefcaseBusiness, ChartNoAxesCombined, CircleGauge,
  History, Pause, Play, Radar, RefreshCw, Settings2, ShieldAlert, SquareActivity,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Empty, ErrorState, Loading, Metric, Money, PageHeader, StatusBadge } from "./components";
import { useData } from "./data";

const navigation = [
  ["/", "Overview", CircleGauge], ["/decisions", "AI Decisions", BrainCircuit],
  ["/positions", "Positions", BriefcaseBusiness], ["/history", "Trade History", History],
  ["/scanner", "Scanner", Radar], ["/risk", "Risk Monitor", ShieldAlert],
  ["/configuration", "Configuration", Settings2],
] as const;

function Shell() {
  const data = useData();
  if (data.loading) return <Loading />;
  if (data.error) return <ErrorState message={data.error} retry={() => void data.refresh()} />;
  return <div className="shell">
    <aside>
      <div className="brand"><div className="mark"><ChartNoAxesCombined size={21} /></div><div><strong>SignalForge</strong><span>Options intelligence</span></div></div>
      <nav>{navigation.map(([path, label, Icon]) => <NavLink key={path} to={path} end={path === "/"}><Icon size={18} /><span>{label}</span></NavLink>)}</nav>
      <div className="side-status"><span className={`dot ${data.connected ? "online" : ""}`} />{data.connected ? "Realtime connected" : "Reconnecting"}</div>
    </aside>
    <main>
      <div className="topbar"><span className="paper">PAPER TRADING</span><span>Execution {data.overview?.execution_enabled ? "enabled" : "locked"}</span></div>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/decisions" element={<Decisions />} />
        <Route path="/positions" element={<Positions />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/scanner" element={<Scanner />} />
        <Route path="/risk" element={<Risk />} />
        <Route path="/configuration" element={<Configuration />} />
      </Routes>
    </main>
  </div>;
}

function AgentControls() {
  const { agent, control } = useData();
  const [pending, setPending] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ error: boolean; message: string } | null>(null);
  const [requestedAction, setRequestedAction] = useState<"start" | "pause" | "scan" | "kill-switch" | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  if (!agent) return null;

  const runControl = async (
    action: "start" | "pause" | "scan" | "kill-switch",
    suppliedToken?: string,
  ) => {
    const token = suppliedToken ?? sessionStorage.getItem("signalforge-control-token") ?? "";
    if (!token) {
      setRequestedAction(action);
      setTokenInput("");
      return;
    }
    setPending(action);
    setFeedback({ error: false, message: action === "scan" ? "Scan running..." : "Updating agent..." });
    try {
      await control(action, token);
      const messages = {
        start: "Agent started.",
        pause: "Agent paused.",
        scan: "Scan completed.",
        "kill-switch": "Kill switch activated.",
      };
      setFeedback({ error: false, message: messages[action] });
    } catch (error) {
      sessionStorage.removeItem("signalforge-control-token");
      setFeedback({
        error: true,
        message: error instanceof Error ? error.message : "Agent command failed",
      });
    } finally {
      setPending(null);
    }
  };

  const submitToken = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const token = tokenInput.trim();
    if (!token || !requestedAction) return;
    sessionStorage.setItem("signalforge-control-token", token);
    const action = requestedAction;
    setRequestedAction(null);
    setTokenInput("");
    void runControl(action, token);
  };

  return <div className="control-group">
    <div className="controls">
      <button className="icon-button" title="Start agent" disabled={Boolean(pending) || agent.effective_state === "RUNNING"} onClick={() => void runControl("start")}><Play size={17} /></button>
      <button className="icon-button" title="Pause agent" disabled={Boolean(pending) || agent.effective_state === "STOPPED"} onClick={() => void runControl("pause")}><Pause size={17} /></button>
      <button className="icon-button" title="Run one scan" disabled={Boolean(pending) || agent.running_cycle || agent.kill_switch_active} onClick={() => void runControl("scan")}><RefreshCw className={pending === "scan" ? "spin" : ""} size={17} /></button>
      <button className="button danger" disabled={Boolean(pending) || agent.kill_switch_active} onClick={() => { if (confirm("Activate the paper-trading kill switch?")) void runControl("kill-switch"); }}><ShieldAlert size={16} />Kill switch</button>
    </div>
    {feedback && <span className={`control-feedback ${feedback.error ? "error" : ""}`} role="status">{feedback.message}</span>}
    {requestedAction && <div className="modal-backdrop" role="presentation">
      <form className="token-dialog" onSubmit={submitToken} role="dialog" aria-modal="true" aria-labelledby="token-dialog-title">
        <h2 id="token-dialog-title">Agent authorization</h2>
        <label htmlFor="control-token">Control token</label>
        <input id="control-token" type="password" value={tokenInput} onChange={(event) => setTokenInput(event.target.value)} autoFocus autoComplete="off" />
        <div className="dialog-actions">
          <button className="button secondary" type="button" onClick={() => setRequestedAction(null)}>Cancel</button>
          <button className="button primary" type="submit" disabled={!tokenInput.trim()}>Authorize</button>
        </div>
      </form>
    </div>}
  </div>;
}

function Overview() {
  const { overview, agent, analytics, candidates, positions } = useData();
  if (!overview || !agent || !analytics) return <Loading />;
  return <>
    <PageHeader title="Trading overview" detail="Portfolio state and autonomous decision flow" action={<AgentControls />} />
    <section className="status-strip"><div><span>Agent</span><StatusBadge value={agent.effective_state} /></div><div><span>Cycle</span><strong>{agent.cycle_state}</strong></div><div><span>Last heartbeat</span><strong>{agent.last_heartbeat ? new Date(agent.last_heartbeat).toLocaleTimeString() : "Not started"}</strong></div><div><span>Mode</span><strong>{agent.autonomy_enabled ? "Autonomous" : "Manual"}</strong></div></section>
    <section className="metrics">
      <Metric label="Portfolio equity"><Money value={overview.equity} /></Metric>
      <Metric label="Daily P&L"><Money value={overview.daily_pnl} signed /></Metric>
      <Metric label="Total P&L"><Money value={overview.total_pnl} signed /></Metric>
      <Metric label="Buying power"><Money value={overview.options_buying_power ?? overview.buying_power} /></Metric>
      <Metric label="Win rate">{(Number(overview.win_rate) * 100).toFixed(1)}%</Metric>
      <Metric label="Open positions">{overview.open_positions}</Metric>
    </section>
    <section className="overview-grid">
      <div className="panel chart-panel"><div className="panel-title"><div><h2>Cumulative P&L</h2><span>Closed paper positions</span></div><SquareActivity size={19} /></div>{analytics.cumulative_pnl.length ? <ResponsiveContainer width="100%" height={260}><LineChart data={analytics.cumulative_pnl}><CartesianGrid stroke="#e4e9ee" vertical={false} /><XAxis dataKey="timestamp" tickFormatter={(value) => new Date(value).toLocaleDateString()} /><YAxis /><Tooltip /><Line type="monotone" dataKey="pnl" stroke="#087e8b" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer> : <Empty title="No P&L history" detail="Filled and closed paper positions will appear here." />}</div>
      <div className="panel"><div className="panel-title"><div><h2>Recent decisions</h2><span>Latest candidate outcomes</span></div><Bot size={19} /></div>{candidates.length ? candidates.slice(0, 5).map((item) => <div className="feed-row" key={item.id}><div><strong>{item.symbol}</strong><span>{item.direction} · score {Number(item.signal_score).toFixed(2)}</span></div><StatusBadge value={item.status} /></div>) : <Empty title="No decisions yet" detail="Run a scan to populate the lifecycle feed." />}</div>
    </section>
    {positions.length > 0 && <PositionTable rows={positions.filter((item) => item.status === "OPEN")} />}
  </>;
}

function Decisions() {
  const { candidates } = useData();
  return <><PageHeader title="AI decision feed" detail="Signal to reasoning, risk, contract, and execution evidence" />{!candidates.length ? <Empty title="No candidate decisions" detail="The feed remains empty until a deterministic scan finds an opportunity." /> : <div className="decision-list">{candidates.map((item) => <article className="decision" key={item.id}><header><div><strong>{item.symbol}</strong><span>{new Date(item.created_at).toLocaleString()}</span></div><StatusBadge value={item.status} /></header><div className="pipeline"><Step label="Market signal" value={`${item.direction} · ${Number(item.signal_score).toFixed(2)}`} /><Step label="AI decision" value={item.ai_decision?.decision ?? "Pending"} /><Step label="Risk" value={item.risk_decisions.at(-1)?.verdict ?? "Pending"} /><Step label="Contract" value={item.contract?.symbol ?? "Not selected"} /></div>{item.ai_decision && <div className="thesis"><strong>{item.ai_decision.thesis}</strong><div><span>Confidence {(Number(item.ai_decision.confidence) * 100).toFixed(0)}%</span><span>{item.ai_metadata?.model}</span></div></div>}</article>)}</div>}</>;
}

function Step({ label, value }: { label: string; value: string }) { return <div className="step"><span>{label}</span><strong>{value}</strong></div>; }

function PositionTable({ rows }: { rows: ReturnType<typeof useData>["positions"] }) {
  return <div className="table-wrap"><table><thead><tr><th>Underlying</th><th>Contract</th><th>Status</th><th>Qty</th><th>Entry</th><th>Current</th><th>P&L</th><th>Expiry</th></tr></thead><tbody>{rows.map((item) => <tr key={item.id}><td><strong>{item.underlying}</strong></td><td className="mono">{item.contract_symbol}</td><td><StatusBadge value={item.status} /></td><td>{item.quantity}</td><td><Money value={item.entry_price} /></td><td><Money value={item.current_price} /></td><td><Money value={item.unrealized_pnl} signed /></td><td>{item.expiration_date}</td></tr>)}</tbody></table></div>;
}

function Positions() { const { positions } = useData(); const open = positions.filter((item) => item.status === "OPEN"); return <><PageHeader title="Open positions" detail="Reconciled long option positions and deterministic exits" />{open.length ? <PositionTable rows={open} /> : <Empty title="No open positions" detail="Only reconciled Alpaca paper positions appear here." />}</>; }

function HistoryPage() { const { positions, orders } = useData(); const closed = positions.filter((item) => item.status === "CLOSED"); return <><PageHeader title="Trade history" detail="Closed positions, realized results, and paper order trail" />{closed.length ? <PositionTable rows={closed} /> : <Empty title="No closed trades" detail="Completed paper position lifecycles will appear here." />}<h2 className="section-title">Order activity</h2>{orders.length ? <div className="table-wrap"><table><thead><tr><th>Time</th><th>Underlying</th><th>Contract</th><th>Intent</th><th>Status</th><th>Qty</th><th>Limit</th></tr></thead><tbody>{orders.map((item) => <tr key={item.id}><td>{new Date(item.created_at).toLocaleString()}</td><td><strong>{item.underlying}</strong></td><td className="mono">{item.contract_symbol}</td><td>{item.intent}</td><td><StatusBadge value={item.status} /></td><td>{item.quantity}</td><td><Money value={item.limit_price} /></td></tr>)}</tbody></table></div> : <Empty title="No orders" detail="No paper orders have been submitted." />}</>; }

function Scanner() {
  const data = useData();
  const watchlist = data.scan?.watchlist ?? data.configuration?.watchlist ?? [];
  const opportunities = new Map(
    (data.scan?.opportunities ?? []).map((item) => [item.symbol, item]),
  );

  return <>
    <PageHeader title="Opportunity scanner" detail="Deterministic quantitative signals across the configured watchlist" action={<button className="button primary" disabled={data.scanning} onClick={() => void data.scanMarket()}>{data.scanning ? <RefreshCw className="spin" size={16} /> : <Radar size={16} />}{data.scanning ? "Scanning..." : "Scan market"}</button>} />
    <div className="watchlist">{watchlist.map((symbol) => <span key={symbol}>{symbol}</span>)}</div>
    {data.scan && <div className="scan-summary" role="status">
      <div><span>Last scan</span><strong>{new Date(data.scan.timestamp).toLocaleTimeString()}</strong></div>
      <div><span>Market</span><StatusBadge value={data.scan.market_open ? "OPEN" : "CLOSED"} /></div>
      <div><span>Qualified</span><strong>{data.scan.opportunities.length} of {data.scan.watchlist.length}</strong></div>
    </div>}
    {data.scan ? <div className="table-wrap"><table>
      <thead><tr><th>Symbol</th><th>Bias</th><th>Score</th><th>Price</th><th>Freshness</th><th>Reasons</th></tr></thead>
      <tbody>{watchlist.map((symbol) => {
        const item = opportunities.get(symbol);
        return <tr key={symbol} className={item ? "opportunity-row" : "no-signal-row"}>
          <td><strong>{symbol}</strong></td>
          <td><StatusBadge value={item ? item.directional_bias.toUpperCase() : "NO SIGNAL"} /></td>
          <td>{item ? Number(item.signal_score).toFixed(3) : "-"}</td>
          <td>{item ? <Money value={item.underlying_price} /> : "-"}</td>
          <td>{item ? `${item.data_freshness_seconds}s` : "-"}</td>
          <td>{item ? item.reasons.join(" | ") : "No qualifying opportunity in this scan."}</td>
        </tr>;
      })}</tbody>
    </table></div> : <Empty title="Scan not run" detail="Run the market scanner to evaluate every configured symbol." />}
  </>;
}

function Risk() { const { candidates } = useData(); const decisions = candidates.flatMap((candidate) => candidate.risk_decisions.map((risk) => ({ candidate, risk }))); return <><PageHeader title="Risk monitor" detail="Every deterministic rule evaluation, including rejected trades" />{decisions.length ? <div className="risk-list">{decisions.map(({ candidate, risk }, index) => <article className="panel" key={`${candidate.id}-${index}`}><div className="panel-title"><div><h2>{candidate.symbol} · {risk.stage}</h2><span>{candidate.status}</span></div><StatusBadge value={risk.verdict} /></div><div className="rule-grid">{risk.evaluations.map((rule) => <div className={rule.passed ? "rule pass" : "rule fail"} key={rule.rule_name}><span>{rule.rule_name.replaceAll("_", " ")}</span><strong>{rule.passed ? "Passed" : "Blocked"}</strong><small>{rule.actual_value} / {rule.limit}</small></div>)}</div></article>)}</div> : <Empty title="No risk evaluations" detail="Risk evidence appears after an AI recommendation requests a trade." />}</>; }

function Configuration() { const { agent, overview, configuration } = useData(); return <><PageHeader title="Agent configuration" detail="Effective runtime controls and immutable safety state" /><div className="config-grid"><Config label="Trading environment" value="Alpaca paper" /><Config label="Autonomous scheduler" value={agent?.autonomy_enabled ? "Enabled" : "Disabled"} /><Config label="Order submission" value={overview?.execution_enabled ? "Enabled" : "Disabled"} /><Config label="Agent state" value={agent?.effective_state ?? "Unknown"} /><Config label="Kill switch" value={agent?.kill_switch_active ? "Active" : "Inactive"} /><Config label="Scan interval" value={`${configuration?.scan_interval_seconds ?? 0}s`} /><Config label="Signal threshold" value={configuration?.signal_threshold ?? "-"} /><Config label="Minimum AI confidence" value={configuration?.minimum_ai_confidence ?? "-"} /><Config label="Premium cap" value={`$${configuration?.maximum_premium_per_trade ?? "-"}`} /><Config label="DTE window" value={configuration?.dte_window.join("–") ?? "-"} /></div><div className="notice"><Activity size={20} /><div><strong>Environment-managed configuration</strong><span>Strategy and risk changes require validated server configuration and restart.</span></div></div></>; }
function Config({ label, value }: { label: string; value: string }) { return <div className="config-row"><span>{label}</span><strong>{value}</strong></div>; }

export default Shell;

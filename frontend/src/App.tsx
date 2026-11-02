import { useEffect, useState } from "react";
import { getEvents, getIncidents, getOverview, Incident, Overview } from "./api";

const severityClass = (severity: string) => `severity severity-${severity}`;

export function App() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState("Overview");

  useEffect(() => {
    const refresh = async () => {
      try {
        const [nextOverview, nextIncidents] = await Promise.all([getOverview(), getIncidents()]);
        setOverview(nextOverview);
        setIncidents(nextIncidents);
        setError(null);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Unable to load dashboard");
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">E</span><span>EDGE-SRE</span></div>
        <p className="eyebrow">OPERATIONS CONSOLE</p>
        {["Overview", "Metrics", "Incidents", "Events", "Remediation", "Audit", "Configuration"].map((item) => (
          <button className={page === item ? "nav active" : "nav"} onClick={() => setPage(item)} key={item}>{item}</button>
        ))}
        <div className="mode"><span className="dot" /> OBSERVE MODE</div>
      </aside>
      <main className="content">
        <header><div><p className="eyebrow">INFRASTRUCTURE / {page.toUpperCase()}</p><h1>{page}</h1></div><div className="host">{overview?.host_id ?? "No host connected"} <span className="online">● LOCAL</span></div></header>
        {error && <div className="error">{error}</div>}
        {page === "Overview" && <OverviewPage overview={overview} incidents={incidents} />}
        {page !== "Overview" && <section className="empty"><h2>{page}</h2><p>This operational view is wired for the Phase 8 API and will be expanded in the next dashboard iteration.</p></section>}
      </main>
    </div>
  );
}

function OverviewPage({ overview, incidents }: { overview: Overview | null; incidents: Incident[] }) {
  const snapshot = overview?.latest_snapshot;
  return <div className="dashboard">
    <div className="cards">
      <MetricCard label="CPU UTILIZATION" value={snapshot ? `${snapshot.cpu_percent.toFixed(1)}%` : "--"} tone="blue" />
      <MetricCard label="MEMORY UTILIZATION" value={snapshot ? `${snapshot.memory_percent.toFixed(1)}%` : "--"} tone="purple" />
      <MetricCard label="ACTIVE INCIDENTS" value={`${overview?.active_incidents ?? 0}`} tone="red" />
      <MetricCard label="EVENTS RETAINED" value={`${overview?.event_count ?? 0}`} tone="green" />
    </div>
    <section className="panel"><div className="panel-heading"><h2>Active incidents</h2><span className="muted">{incidents.length} tracked</span></div>
      {incidents.length === 0 ? <p className="muted">No active incidents. Monitoring is healthy.</p> : incidents.map((incident) => <div className="incident" key={incident.incident_id}><span className={severityClass(incident.severity)}>{incident.severity}</span><strong>{incident.title}</strong><span className="muted">{incident.status}</span></div>)}
    </section>
    <section className="grid-two"><div className="panel"><div className="panel-heading"><h2>Severity distribution</h2></div>{(["critical", "high", "warning", "info"] as const).map((level) => <div className="bar-row" key={level}><span>{level}</span><div className="bar"><i className={`fill fill-${level}`} style={{ width: `${Math.min(100, (overview?.severity_distribution[level] ?? 0) * 20)}%` }} /></div><b>{overview?.severity_distribution[level] ?? 0}</b></div>)}</div><div className="panel"><div className="panel-heading"><h2>System status</h2></div><div className="status-row"><span className="dot" /> Local monitoring active</div><div className="status-row"><span className="dot" /> Event processing active</div><div className="status-row"><span className="dot muted-dot" /> Ollama optional</div></div></section>
  </div>;
}

function MetricCard({ label, value, tone }: { label: string; value: string; tone: string }) {
  return <div className="metric-card"><span className={`metric-icon ${tone}`} /><p>{label}</p><strong>{value}</strong><small>latest observation</small></div>;
}

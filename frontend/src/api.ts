export type Severity = "info" | "warning" | "high" | "critical";

export interface Snapshot {
  host_id: string;
  cpu_percent: number;
  memory_percent: number;
  swap_percent: number;
  disks: Record<string, number>;
  uptime_seconds: number;
}

export interface Incident {
  incident_id: string;
  title: string;
  severity: Severity;
  status: string;
  first_seen: string;
  last_seen: string;
}

export interface Overview {
  host_id: string | null;
  active_incidents: number;
  severity_distribution: Record<Severity, number>;
  event_count: number;
  latest_snapshot: Snapshot | null;
}

const api = async <T,>(path: string): Promise<T> => {
  const response = await fetch(`/api${path}`);
  if (!response.ok) throw new Error(`API request failed: ${response.status}`);
  return response.json() as Promise<T>;
};

export const getOverview = () => api<Overview>("/overview");
export const getIncidents = () => api<Incident[]>("/incidents?active_only=true");
export const getEvents = () => api<unknown[]>("/events?limit=100");


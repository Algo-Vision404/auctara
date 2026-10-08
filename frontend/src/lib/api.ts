import type {
  Agent,
  DashboardSummary,
  Policy,
  PolicyDraft,
  Task,
  Transaction,
  AuditRecord,
  ScheduledTask,
  Recurrence,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiError(
      `Could not reach AgentAuth backend. Is it running? (${(err as Error).message})`,
      0
    );
  }

  if (!res.ok) {
    let detail = `Request failed (HTTP ${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; paypal_configured: boolean; openrouter_configured: boolean; paypal_environment: string; model: string }>("/health"),

  dashboardSummary: () => request<DashboardSummary>("/dashboard/summary"),

  listAgents: () => request<Agent[]>("/agents"),
  getAgent: (id: string) => request<Agent>(`/agents/${id}`),
  draftPolicy: (instructions: string) =>
    request<PolicyDraft>("/agents/draft-policy", {
      method: "POST",
      body: JSON.stringify({ instructions }),
    }),
  createAgent: (payload: { name: string; purpose: string; directive: string; policy: Omit<PolicyDraft, "agent_name" | "agent_purpose"> }) =>
    request<Agent>("/agents", { method: "POST", body: JSON.stringify(payload) }),

  listTasks: (agentId?: string) => request<Task[]>(`/tasks${agentId ? `?agent_id=${agentId}` : ""}`),
  getTask: (id: string) => request<Task>(`/tasks/${id}`),
  createTask: (payload: { agent_id: string; prompt: string; max_amount?: number | null }) =>
    request<Task>("/tasks", { method: "POST", body: JSON.stringify(payload) }),

  recentActivity: (limit = 50, taskId?: string) =>
    request(`/activity?limit=${limit}${taskId ? `&task_id=${taskId}` : ""}`),

  listTransactions: (params?: { agent_id?: string; state?: string; decision?: string }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return request<Transaction[]>(`/transactions${qs ? `?${qs}` : ""}`);
  },
  getTransaction: (id: string) => request<Transaction>(`/transactions/${id}`),
  approveTransaction: (id: string) => request<Transaction>(`/transactions/${id}/approve`, { method: "POST" }),
  rejectTransaction: (id: string, reason?: string) =>
    request<Transaction>(`/transactions/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  continuePaypal: (id: string) => request<Transaction>(`/transactions/${id}/paypal/continue`, { method: "POST" }),

  getPolicy: (agentId: string) => request<Policy>(`/policies/${agentId}`),
  updatePolicy: (agentId: string, payload: Omit<PolicyDraft, "agent_name" | "agent_purpose">) =>
    request<Policy>(`/policies/${agentId}`, { method: "PUT", body: JSON.stringify(payload) }),
  evaluatePolicy: (payload: { agent_id: string; amount: number; category: string }) =>
    request(`/policies/evaluate`, { method: "POST", body: JSON.stringify(payload) }),

  listAudit: (params?: { transaction_id?: string; limit?: number }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return request<AuditRecord[]>(`/audit${qs ? `?${qs}` : ""}`);
  },
  verifyAudit: () => request<{ valid: boolean; records_verified?: number; broken_at_seq?: number }>("/audit/verify"),

  listSchedules: (agentId?: string) =>
    request<ScheduledTask[]>(`/schedules${agentId ? `?agent_id=${agentId}` : ""}`),
  createSchedule: (payload: { agent_id: string; prompt: string; max_amount?: number | null; recurrence: Recurrence; start_at?: string }) =>
    request<ScheduledTask>("/schedules", { method: "POST", body: JSON.stringify(payload) }),
  updateSchedule: (id: string, payload: { status: "ACTIVE" | "PAUSED" | "CANCELLED" }) =>
    request<ScheduledTask>(`/schedules/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteSchedule: (id: string) => request<{ deleted: boolean }>(`/schedules/${id}`, { method: "DELETE" }),
};

export interface StreamEvent {
  event: string;
  timestamp?: string;
  task_id?: string | null;
  transaction_id?: string | null;
  agent_id?: string | null;
  message?: string;
  payload?: Record<string, unknown>;
  status?: string;
}

export function subscribeToEvents(
  path: string,
  onEvent: (event: StreamEvent) => void,
  onConnectionChange?: (connected: boolean) => void
): () => void {
  const es = new EventSource(`/api${path}`);
  es.onmessage = (e: MessageEvent) => {
    try {
      const parsed = JSON.parse(e.data) as StreamEvent;
      if (parsed.event === "CONNECTED") {
        onConnectionChange?.(true);
        return;
      }
      onEvent(parsed);
    } catch {
      /* ignore malformed event */
    }
  };
  es.onerror = () => {
    onConnectionChange?.(false);
  };
  return () => es.close();
}

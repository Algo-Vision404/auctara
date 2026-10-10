import type {
  Agent,
  DashboardSummary,
  DraftConversationMessage,
  DraftPolicyResponse,
  Policy,
  PolicyDraft,
  Task,
  Transaction,
  AuditRecord,
  ScheduledTask,
  ScheduleRun,
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
  } catch {
    // Deliberately no raw browser/fetch error text here (e.g. "Failed to
    // fetch", "NetworkError when attempting to fetch resource"): it's
    // noise to anyone but a developer, and this single message already
    // says exactly what the user needs to know.
    throw new ApiError("Could not reach the AgentAuth backend. Is it running?", 0);
  }

  if (!res.ok) {
    let detail = `Request failed (HTTP ${res.status})`;
    try {
      const body = await res.json();
      // FastAPI's own validation errors (422s from a bad request body) put
      // an array of {loc, msg, type} objects in `detail` rather than a
      // string. Every error we deliberately raise ourselves (HTTPException)
      // always uses a plain string, so a non-string here only ever means
      // "the framework generated this, not us" - stringify it into
      // something readable instead of letting an array/object reach the
      // UI as literal "[object Object]" text.
      if (typeof body.detail === "string" && body.detail) {
        detail = body.detail;
      } else if (Array.isArray(body.detail) && body.detail.length) {
        detail = body.detail
          .map((d: { msg?: string }) => d.msg)
          .filter(Boolean)
          .join("; ") || detail;
      }
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
  // Two ways to call this: starting a fresh drafting conversation
  // ({ instructions }), or continuing one after the AI asked a clarifying
  // question ({ conversation, answer }), where `conversation` is exactly
  // what the previous response returned. Either can come back "ready"
  // (a finished draft) or "needs_clarification" (one more question) -
  // there is no separate endpoint for the two, since it is genuinely the
  // same conversation, just possibly several turns long.
  draftPolicy: (payload: { instructions: string } | { conversation: DraftConversationMessage[]; answer: string }) =>
    request<DraftPolicyResponse>("/agents/draft-policy", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createAgent: (payload: { name: string; purpose: string; directive: string; policy: Omit<PolicyDraft, "agent_name" | "agent_purpose"> }) =>
    request<Agent>("/agents", { method: "POST", body: JSON.stringify(payload) }),
  retireAgent: (id: string) => request<Agent>(`/agents/${id}/retire`, { method: "POST" }),
  reactivateAgent: (id: string) => request<Agent>(`/agents/${id}/reactivate`, { method: "POST" }),
  deleteAgent: (id: string) => request<{ deleted: boolean }>(`/agents/${id}`, { method: "DELETE" }),

  listTasks: (agentId?: string) => request<Task[]>(`/tasks${agentId ? `?agent_id=${agentId}` : ""}`),
  getTask: (id: string) => request<Task>(`/tasks/${id}`),
  createTask: (payload: {
    agent_id: string;
    prompt: string;
    max_amount?: number | null;
    paypal_negative_test?: string | null;
  }) => request<Task>("/tasks", { method: "POST", body: JSON.stringify(payload) }),
  negativeTestOptions: () => request<{ code: string; description: string }[]>("/tasks/negative-test-options"),
  respondToTask: (id: string, message: string) =>
    request<{ status: string }>(`/tasks/${id}/respond`, { method: "POST", body: JSON.stringify({ message }) }),

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
  listScheduleRuns: (id: string) => request<ScheduleRun[]>(`/schedules/${id}/runs`),
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

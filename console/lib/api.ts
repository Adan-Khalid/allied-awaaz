"use client";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const TOKEN_KEY = "awaaz.staff.token";

export type Role = "rm" | "supervisor";
export type HealthStatus = "HEALTHY" | "WATCH" | "AT_RISK";
export type ReasonCode = "NEVER_ACTIVATED" | "DORMANT" | "DECLINING" | "DEVICE_OFFLINE" | "EXCEPTION_SPIKE";

export interface Staff { name: string; role: Role }

export interface Metrics {
  txn_7d: number;
  baseline_weekly_txn: number;
  volume_7d_rupees: number;
  days_since_last_payment: number | null;
  exceptions_14d: number;
  device_offline_hours: number | null;
  onboarded_days: number;
}

export interface MerchantRow {
  id: string; name: string; category: string; city: string; rm_name: string;
  score: number; status: HealthStatus; primary_reason: ReasonCode | null; flags: ReasonCode[]; metrics: Metrics;
}

export interface Flag { code: ReasonCode; detail: string; evidence: Record<string, number | null> }

export interface Health {
  merchant_id: string; merchant_name: string; score: number; status: HealthStatus;
  primary_reason: ReasonCode | null; flags: Flag[]; metrics: Metrics;
}

export interface MerchantDetail {
  merchant: { id: string; name: string; category: string; city: string; phone_masked: string; rm_name: string; onboarded_at: string };
  health: Health;
  devices: { id: string; online: boolean; last_seen_at: string | null; firmware: string }[];
  recent_payments: { txn_id: string; amount_rupees: number; status: string; reference: string; created_at: string; payer_bank: string | null }[];
}

export type Channel = "rm_call" | "field_visit" | "whatsapp" | "ops_review";
export type InterventionStatus = "PENDING_APPROVAL" | "APPROVED" | "EXECUTED" | "REJECTED";

export interface Intervention {
  id: string; merchant_id: string; merchant_name: string | null; reason_code: ReasonCode; channel: Channel;
  title: string; message: string; status: InterventionStatus; agent_run_id: string | null; created_at: string;
  decided_by: string | null; decision_note: string | null; decided_at: string | null;
  evidence: { score: number; status: HealthStatus; flags: Flag[]; metrics: Metrics };
}

export interface ExceptionCase {
  id: string; merchant_id: string; merchant_name: string; type: "CLAIM_NOT_FOUND" | "PENDING_AT_PAYER" | "PAYMENT_FAILED";
  status: "OPEN" | "AUTO_RESOLVED" | "CLOSED"; claimed_amount_rupees: number; payment_id: string | null;
  agent_run_id: string | null; opened_at: string; resolution: string | null;
}

export interface TraceStep { step: string; [k: string]: unknown }

export interface AgentRun {
  id: string; agent: "merchant" | "activation"; merchant_id: string | null; device_id?: string | null;
  input_text: string | null; intent: string | null; understood_by: string | null; outcome: string | null;
  steps: TraceStep[]; created_at: string;
}

export interface AuditEntry { at: string; actor: string; action: string; subject: string | null; detail: Record<string, unknown> }

export interface Summary {
  merchants: Record<HealthStatus, number>; pending_approvals: number; open_exceptions: number;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export const session = {
  get: (): string | null => (typeof window === "undefined" ? null : window.sessionStorage.getItem(TOKEN_KEY)),
  set: (t: string) => window.sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => window.sessionStorage.removeItem(TOKEN_KEY),
};

export async function api<T>(path: string, init: { method?: "GET" | "POST"; body?: unknown; token?: string } = {}): Promise<T> {
  const token = init.token ?? session.get();
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: init.method ?? "GET",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `Can't reach the Awaaz backend at ${API_BASE}. Check that it is running.`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* non-JSON error */ }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

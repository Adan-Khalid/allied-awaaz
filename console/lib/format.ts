"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type Channel, type HealthStatus, type ReasonCode } from "./api";

export const REASON_LABEL: Record<ReasonCode, string> = {
  NEVER_ACTIVATED: "Never activated",
  DORMANT: "Dormant",
  DECLINING: "Usage declining",
  DEVICE_OFFLINE: "Terminal offline",
  EXCEPTION_SPIKE: "Repeated payment disputes",
};

export const CHANNEL_LABEL: Record<Channel, string> = {
  rm_call: "RM call",
  field_visit: "Field visit",
  whatsapp: "WhatsApp message to merchant",
  ops_review: "Ops review",
};

export const CHANNEL_APPROVERS: Record<Channel, string> = {
  rm_call: "RM or supervisor",
  field_visit: "RM or supervisor",
  ops_review: "RM or supervisor",
  whatsapp: "Supervisor only",
};

export const STATUS_LABEL: Record<HealthStatus, string> = { HEALTHY: "Healthy", WATCH: "Watch", AT_RISK: "At risk" };

export const CASE_LABEL: Record<string, string> = {
  CLAIM_NOT_FOUND: "Claimed, not received",
  PENDING_AT_PAYER: "Pending at payer bank",
  PAYMENT_FAILED: "Payment failed",
};

export const OUTCOME_LABEL: Record<string, string> = {
  QR_READY: "QR created",
  CLAIM_RECEIVED: "Claim verified: received",
  CLAIM_PENDING: "Claim: pending at payer bank",
  CLAIM_FAILED: "Claim: payment failed",
  CLAIM_NOT_RECEIVED: "Claim: not received",
  LAST_PAYMENT: "Answered last payment",
  TODAY_SUMMARY: "Answered today's total",
  NO_PAYMENTS: "No payments yet",
  AWAITING_CONFIRMATION: "Waiting for merchant to confirm",
  CLARIFY_AMOUNT: "Asked merchant to repeat amount",
  OUT_OF_SCOPE: "Refused: outside scope",
  TOOL_ERROR: "Rejected by validation",
  VERIFY_FAILED: "Verification failed",
  DEVICE_STATUS: "Reported device status",
  HELP: "Gave help",
  SWEEP_DONE: "Activation sweep complete",
};

export const pkr = (n: number) => `PKR ${n.toLocaleString("en-PK")}`;

export function when(iso: string): string {
  // Backend stores naive UTC.
  const d = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`;
  return d.toLocaleDateString("en-PK", { day: "numeric", month: "short" });
}

export function clock(iso: string): string {
  const d = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  return d.toLocaleString("en-PK", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** Fetch now, then every `intervalMs` while the tab is visible. Keeps the console live during the demo. */
export function usePoll<T>(load: () => Promise<T>, intervalMs = 5000, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  const refresh = useCallback(async () => {
    try {
      setData(await loadRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
    }
  }, []);

  useEffect(() => {
    refresh();
    if (!intervalMs) return;
    const id = window.setInterval(() => { if (document.visibilityState === "visible") refresh(); }, intervalMs);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, intervalMs, ...deps]);

  return { data, error, refresh };
}

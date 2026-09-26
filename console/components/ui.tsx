"use client";

import type { Flag, HealthStatus, Metrics } from "@/lib/api";
import { REASON_LABEL, STATUS_LABEL, pkr } from "@/lib/format";

export function Status({ value, label }: { value: string; label?: string }) {
  return <span className={`status ${value}`}>{label ?? STATUS_LABEL[value as HealthStatus] ?? value.replace(/_/g, " ").toLowerCase()}</span>;
}

export function Score({ score }: { score: number }) {
  const colour = score >= 80 ? "var(--green)" : score >= 50 ? "var(--amber)" : "var(--brick)";
  return (
    <div className="score" aria-label={`Health score ${score} of 100`}>
      <b>{score}</b>
      <span className="bar"><i style={{ width: `${score}%`, background: colour }} /></span>
    </div>
  );
}

export function Flags({ flags, primary }: { flags: Flag[]; primary: string | null }) {
  if (!flags.length) return <p className="muted">No risk signals. Activity is in line with this merchant's usual pattern.</p>;
  return (
    <div className="flags">
      {flags.map((f) => (
        <div key={f.code} className={`flag ${f.code === primary ? "primary" : ""}`}>
          <strong>{REASON_LABEL[f.code]}{f.code === primary ? " (main reason)" : ""}</strong>
          <span>{f.detail}</span>
        </div>
      ))}
    </div>
  );
}

export function MetricGrid({ m }: { m: Metrics }) {
  const items: [string, string][] = [
    ["Payments, last 7 days", String(m.txn_7d)],
    ["Usual per week", String(m.baseline_weekly_txn)],
    ["Volume, last 7 days", pkr(m.volume_7d_rupees)],
    ["Days since last payment", m.days_since_last_payment === null ? "Never paid" : String(m.days_since_last_payment)],
    ["Disputes, 14 days", String(m.exceptions_14d)],
    ["Terminal", m.device_offline_hours === null ? "None assigned" : m.device_offline_hours < 1 ? "Online" : `Offline ${Math.round(m.device_offline_hours)} h`],
  ];
  return (
    <div className="metrics">
      {items.map(([label, value]) => <div key={label}><b>{value}</b><span>{label}</span></div>)}
    </div>
  );
}

export function ErrorNote({ error }: { error: { message: string } | null }) {
  return error ? <div className="notice error" role="alert">{error.message}</div> : null;
}

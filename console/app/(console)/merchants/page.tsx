"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ErrorNote, Score, Status } from "@/components/ui";
import { api, type HealthStatus, type MerchantRow, type Summary } from "@/lib/api";
import { REASON_LABEL, pkr, usePoll } from "@/lib/format";

type Filter = "ALL" | HealthStatus;

export default function Merchants() {
  const router = useRouter();
  const { data: rows, error, refresh } = usePoll(() => api<MerchantRow[]>("/v1/console/merchants"), 8000);
  const { data: summary, refresh: refreshSummary } = usePoll(() => api<Summary>("/v1/console/summary"), 8000);
  const [filter, setFilter] = useState<Filter>("ALL");
  const [sweeping, setSweeping] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [sweepError, setSweepError] = useState<string | null>(null);

  const shown = useMemo(() => (rows ?? []).filter((r) => filter === "ALL" || r.status === filter), [rows, filter]);

  async function sweep() {
    setSweeping(true);
    setSweepError(null);
    try {
      const r = await api<{ run_id: string; examined: number; drafted: string[] }>("/v1/console/activation/sweep", { method: "POST" });
      setResult(r.drafted.length
        ? `Checked ${r.examined} merchants. ${r.drafted.length} interventions are waiting for approval.`
        : `Checked ${r.examined} merchants. Every flagged merchant already has an open intervention.`);
      refresh();
      refreshSummary();
    } catch (e) {
      setSweepError((e as Error).message);
    } finally {
      setSweeping(false);
    }
  }

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Merchants</h1>
          <p>Health is scored from each merchant's own verified payment history. Flagged merchants come first.</p>
        </div>
        <button className="btn primary" onClick={sweep} disabled={sweeping}>
          {sweeping ? "Checking merchants..." : "Find merchants who need attention"}
        </button>
      </div>

      {result && (
        <div className="notice ok" role="status">
          {result} <Link href="/approvals">Review approvals</Link>
        </div>
      )}
      <ErrorNote error={sweepError ? { message: sweepError } : error} />

      {summary && (
        <div className="strip">
          <div className="risk"><b>{summary.merchants.AT_RISK}</b><span>At risk</span></div>
          <div className="watch"><b>{summary.merchants.WATCH}</b><span>Watch</span></div>
          <div className="ok"><b>{summary.merchants.HEALTHY}</b><span>Healthy</span></div>
          <div><b>{summary.pending_approvals}</b><span>Waiting for approval</span></div>
          <div><b>{summary.open_exceptions}</b><span>Open payment disputes</span></div>
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="Filter by health">
        {(["ALL", "AT_RISK", "WATCH", "HEALTHY"] as Filter[]).map((f) => (
          <button key={f} role="tab" aria-selected={filter === f} onClick={() => setFilter(f)}>
            {f === "ALL" ? "All" : f === "AT_RISK" ? "At risk" : f === "WATCH" ? "Watch" : "Healthy"}
          </button>
        ))}
      </div>

      {rows && (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>Merchant</th><th>Health</th><th>Score</th><th>Main reason</th>
                <th className="num">7-day payments</th><th className="num">7-day volume</th><th>RM</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((m) => (
                <tr key={m.id} className="link" onClick={() => router.push(`/merchants/${m.id}`)}>
                  <td>
                    <div className="name"><Link href={`/merchants/${m.id}`} onClick={(e) => e.stopPropagation()}>{m.name}</Link></div>
                    <div className="muted small">{m.category.replace("_", " ")}, {m.city}</div>
                  </td>
                  <td><Status value={m.status} /></td>
                  <td><Score score={m.score} /></td>
                  <td>{m.primary_reason ? REASON_LABEL[m.primary_reason] : <span className="muted">None</span>}</td>
                  <td className="num">{m.metrics.txn_7d} <span className="muted small">/ usual {m.metrics.baseline_weekly_txn}</span></td>
                  <td className="num">{pkr(m.metrics.volume_7d_rupees)}</td>
                  <td className="nowrap">{m.rm_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!shown.length && <div className="empty">No merchants in this group.</div>}
        </div>
      )}
    </>
  );
}

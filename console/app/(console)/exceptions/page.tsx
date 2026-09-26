"use client";

import Link from "next/link";
import { useState } from "react";
import Trace from "@/components/Trace";
import { ErrorNote, Status } from "@/components/ui";
import { api, type AgentRun, type ExceptionCase } from "@/lib/api";
import { CASE_LABEL, clock, pkr, usePoll, when } from "@/lib/format";

const EXPLAIN: Record<ExceptionCase["type"], string> = {
  CLAIM_NOT_FOUND: "Customer said they paid, but no payment for this amount reached the bank in the search window. Merchant was told not to release goods.",
  PENDING_AT_PAYER: "Payment started but the customer's bank has not confirmed it. Closes automatically when the bank settles.",
  PAYMENT_FAILED: "The customer's bank declined or failed the payment. Merchant was told to ask for a new payment.",
};

export default function Exceptions() {
  const [status, setStatus] = useState<"OPEN" | "">("OPEN");
  const { data, error } = usePoll(() => api<ExceptionCase[]>(`/v1/console/exceptions${status ? `?status=${status}` : ""}`), 4000, [status]);
  const [openRun, setOpenRun] = useState<AgentRun | null>(null);
  const [openCase, setOpenCase] = useState<ExceptionCase | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  async function showRun(id: string) {
    setRunError(null);
    try { setOpenRun(await api<AgentRun>(`/v1/console/agent-runs/${id}`)); } catch (e) { setRunError((e as Error).message); }
  }

  const notFound30 = (data ?? []).filter((c) => c.type === "CLAIM_NOT_FOUND").length;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Payment disputes</h1>
          <p>Raised by terminals when a merchant asks whether a customer's payment arrived. Repeated unpaid claims at one shop can point to screenshot fraud.</p>
        </div>
      </div>
      <ErrorNote error={error ?? (runError ? { message: runError } : null)} />
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={status === "OPEN"} onClick={() => setStatus("OPEN")}>Open</button>
        <button role="tab" aria-selected={status === ""} onClick={() => setStatus("")}>All</button>
      </div>
      {data && data.length > 0 && (
        <p className="muted small">{data.length} cases shown, {notFound30} of them claims where no payment arrived.</p>
      )}
      <div className="grid2" style={{ gridTemplateColumns: "minmax(0, 1.3fr) minmax(0, 1fr)" }}>
        <div className="tablewrap">
          <table style={{ minWidth: 0 }}>
            <thead><tr><th>Merchant</th><th>What happened</th><th className="num">Amount</th><th>Status</th><th>Opened</th></tr></thead>
            <tbody>
              {(data ?? []).map((c) => (
                <tr key={c.id} className="link" onClick={() => { setOpenCase(c); if (c.agent_run_id) showRun(c.agent_run_id); else setOpenRun(null); }}
                  aria-selected={openRun?.id === c.agent_run_id}>
                  <td><div className="name" style={{ minWidth: 0 }}><Link href={`/merchants/${c.merchant_id}`} onClick={(e) => e.stopPropagation()}>{c.merchant_name}</Link></div></td>
                  <td>
                    <b className="small">{CASE_LABEL[c.type]}</b>
                    {c.resolution && <div className="muted small">{c.resolution}</div>}
                  </td>
                  <td className="num nowrap">{pkr(c.claimed_amount_rupees)}</td>
                  <td><Status value={c.status} /></td>
                  <td className="nowrap" title={clock(c.opened_at)}>{when(c.opened_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data && !data.length && <div className="empty">No {status ? "open " : ""}disputes. Cases appear here the moment a terminal raises one.</div>}
        </div>
        <aside className="panel">
          {openCase && (
            <>
              <h2>{CASE_LABEL[openCase.type]}: {pkr(openCase.claimed_amount_rupees)}</h2>
              <p className="small">{EXPLAIN[openCase.type]}</p>
            </>
          )}
          {openRun ? <Trace run={openRun} />
            : openCase ? <p className="muted small">This case was imported without an agent trace.</p>
            : <p className="muted">Select a case to see what happened and every step the agent took before answering the merchant.</p>}
        </aside>
      </div>
    </>
  );
}

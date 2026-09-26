"use client";

import Link from "next/link";
import { useState } from "react";
import Trace from "@/components/Trace";
import { useStaff } from "@/components/staff";
import { ErrorNote, Flags, MetricGrid, Status } from "@/components/ui";
import { api, type AgentRun, type Intervention } from "@/lib/api";
import { CHANNEL_APPROVERS, CHANNEL_LABEL, REASON_LABEL, clock, usePoll, when } from "@/lib/format";

function canApprove(role: string | undefined, i: Intervention) {
  return i.channel === "whatsapp" ? role === "supervisor" : role === "rm" || role === "supervisor";
}

function Card({ item, onDone }: { item: Intervention; onDone: (msg: string) => void }) {
  const staff = useStaff();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [showRun, setShowRun] = useState(false);
  const allowed = canApprove(staff?.role, item);
  const pending = item.status === "PENDING_APPROVAL";

  async function decide(verdict: "approve" | "reject") {
    setBusy(verdict);
    setError(null);
    try {
      await api(`/v1/console/interventions/${item.id}/${verdict}`, { method: "POST", body: { note: note || null } });
      onDone(verdict === "approve"
        ? `Approved and sent: ${CHANNEL_LABEL[item.channel]} for ${item.merchant_name}.`
        : `Rejected: ${CHANNEL_LABEL[item.channel]} for ${item.merchant_name}.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function toggleRun() {
    if (!showRun && !run && item.agent_run_id) {
      try { setRun(await api<AgentRun>(`/v1/console/agent-runs/${item.agent_run_id}`)); } catch (e) { setError((e as Error).message); }
    }
    setShowRun((v) => !v);
  }

  return (
    <article className="approval">
      <div className="body">
        <h2>{item.title}</h2>
        <div className="meta">
          <Link href={`/merchants/${item.merchant_id}`}>{item.merchant_name}</Link>
          {", "}{REASON_LABEL[item.reason_code]}, drafted {when(item.created_at)} by the activation agent
        </div>
        <b className="small">{CHANNEL_LABEL[item.channel]}</b>
        <div className={`message ${item.channel === "whatsapp" ? "whatsapp" : ""}`}>{item.message}</div>
        <Flags flags={item.evidence.flags} primary={item.reason_code} />
        <div style={{ marginTop: 16 }}><MetricGrid m={item.evidence.metrics} /></div>
        {item.agent_run_id && (
          <p><button className="btn" onClick={toggleRun} aria-expanded={showRun}>{showRun ? "Hide agent reasoning" : "Show agent reasoning"}</button></p>
        )}
        {showRun && run && <div className="panel" style={{ marginBottom: 0 }}><Trace run={run} /></div>}
      </div>

      <div className="decide">
        {pending ? (
          <>
            <div className="small"><b>Who can approve:</b> {CHANNEL_APPROVERS[item.channel]}</div>
            {!allowed && (
              <div className="notice error small" style={{ margin: 0 }}>
                Messages sent directly to merchants need a supervisor. You can still reject this draft.
              </div>
            )}
            <label className="small" htmlFor={`note-${item.id}`}><b>Note</b> (saved in the audit log)</label>
            <textarea id={`note-${item.id}`} className="text" value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Called owner, terminal was unplugged" />
            <ErrorNote error={error ? { message: error } : null} />
            <div className="row">
              <button className="btn approve" onClick={() => decide("approve")} disabled={!allowed || busy !== null}>
                {busy === "approve" ? "Approving..." : "Approve and send"}
              </button>
              <button className="btn reject" onClick={() => decide("reject")} disabled={busy !== null}>
                {busy === "reject" ? "Rejecting..." : "Reject"}
              </button>
            </div>
          </>
        ) : (
          <>
            <Status value={item.status} />
            <div className="small">{item.decided_by} {item.decided_at && `, ${clock(item.decided_at)}`}</div>
            {item.decision_note && <div className="small">&ldquo;{item.decision_note}&rdquo;</div>}
            {item.status === "EXECUTED" && <div className="muted small">Dispatched to the {CHANNEL_LABEL[item.channel].toLowerCase()} queue (simulated in this demo).</div>}
          </>
        )}
      </div>
    </article>
  );
}

export default function Approvals() {
  const [tab, setTab] = useState<"waiting" | "decided">("waiting");
  const { data, error, refresh } = usePoll(() => api<Intervention[]>("/v1/console/interventions"), 6000);
  const [flash, setFlash] = useState<string | null>(null);
  const waiting = (data ?? []).filter((i) => i.status === "PENDING_APPROVAL");
  const decided = (data ?? []).filter((i) => i.status !== "PENDING_APPROVAL");
  const list = tab === "waiting" ? waiting : decided;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Approvals</h1>
          <p>The activation agent drafts each intervention with the evidence behind it. Nothing reaches a merchant until someone here approves it.</p>
        </div>
      </div>
      {flash && <div className="notice ok" role="status">{flash}</div>}
      <ErrorNote error={error} />
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "waiting"} onClick={() => setTab("waiting")}>Waiting ({waiting.length})</button>
        <button role="tab" aria-selected={tab === "decided"} onClick={() => setTab("decided")}>Decided ({decided.length})</button>
      </div>
      {data && !list.length && (
        <div className="empty panel">
          {tab === "waiting"
            ? <>Nothing waiting. Run <Link href="/merchants">Find merchants who need attention</Link> to check the merchant base.</>
            : <>No decisions yet.</>}
        </div>
      )}
      {list.map((i) => <Card key={i.id} item={i} onDone={(m) => { setFlash(m); refresh(); }} />)}
    </>
  );
}

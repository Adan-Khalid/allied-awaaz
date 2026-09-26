"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Trace from "@/components/Trace";
import { ErrorNote, Flags, MetricGrid, Score, Status } from "@/components/ui";
import { api, type AgentRun, type ExceptionCase, type Intervention, type MerchantDetail } from "@/lib/api";
import { CASE_LABEL, CHANNEL_LABEL, OUTCOME_LABEL, clock, pkr, usePoll, when } from "@/lib/format";

export default function MerchantPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error } = usePoll(() => api<MerchantDetail>(`/v1/console/merchants/${id}`), 5000, [id]);
  const { data: runs } = usePoll(() => api<AgentRun[]>(`/v1/console/agent-runs?merchant_id=${id}&limit=30`), 5000, [id]);
  const { data: interventions } = usePoll(() => api<Intervention[]>("/v1/console/interventions"), 8000);
  const { data: cases } = usePoll(() => api<ExceptionCase[]>("/v1/console/exceptions"), 5000);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!selected && runs?.length) setSelected(runs[0].id);
  }, [runs, selected]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return null;
  const { merchant: m, health: h } = data;
  const mine = (interventions ?? []).filter((i) => i.merchant_id === m.id);
  const myCases = (cases ?? []).filter((c) => c.merchant_id === m.id).slice(0, 8);
  const run = runs?.find((r) => r.id === selected) ?? null;

  return (
    <>
      <p className="small"><Link href="/merchants">Merchants</Link></p>
      <div className="pagehead">
        <div>
          <h1>{m.name}</h1>
          <p>{m.category.replace("_", " ")}, {m.city}. Relationship manager {m.rm_name}.</p>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <Status value={h.status} />
          <Score score={h.score} />
        </div>
      </div>

      <div className="grid2">
        <div>
          <section className="panel">
            <h2>Why this score</h2>
            <Flags flags={h.flags} primary={h.primary_reason} />
            <h3>Signals from the payment ledger</h3>
            <MetricGrid m={h.metrics} />
          </section>

          <section className="panel">
            <h2>What the terminal agent did</h2>
            {!runs?.length ? (
              <p className="muted">No agent activity yet. Actions from this merchant's terminal appear here as they happen.</p>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 190px) minmax(0, 1fr)", gap: 20 }}>
                <div className="runlist" role="tablist" aria-label="Agent runs">
                  {runs.map((r) => (
                    <button key={r.id} role="tab" aria-selected={r.id === selected} onClick={() => setSelected(r.id)}>
                      <b className="small">{OUTCOME_LABEL[r.outcome ?? ""] ?? r.outcome}</b>
                      <span>{r.input_text ? `"${r.input_text.slice(0, 42)}"` : "Keypad"}, {when(r.created_at)}</span>
                    </button>
                  ))}
                </div>
                <div>{run && <Trace run={run} />}</div>
              </div>
            )}
          </section>

          <section className="panel">
            <h2>Recent payments</h2>
            <div className="tablewrap">
              <table>
                <thead><tr><th>When</th><th className="num">Amount</th><th>Status</th><th>Reference</th><th>Payer bank</th></tr></thead>
                <tbody>
                  {data.recent_payments.map((p) => (
                    <tr key={p.txn_id}>
                      <td>{clock(p.created_at)}</td>
                      <td className="num">{pkr(p.amount_rupees)}</td>
                      <td><Status value={p.status === "SUCCEEDED" ? "HEALTHY" : p.status === "PENDING" || p.status === "CREATED" ? "WATCH" : "AT_RISK"}
                        label={p.status.toLowerCase()} /></td>
                      <td className="muted">{p.reference}</td>
                      <td>{p.payer_bank ?? <span className="muted">n/a</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <aside>
          <section className="panel">
            <h2>Account</h2>
            <dl className="facts">
              <dt>Phone</dt><dd>{m.phone_masked}</dd>
              <dt>Onboarded</dt><dd>{clock(m.onboarded_at)}</dd>
              <dt>RM</dt><dd>{m.rm_name}</dd>
            </dl>
            <h3>Terminals</h3>
            {data.devices.map((d) => {
              const live = d.online || (d.last_seen_at !== null && Date.now() - new Date(`${d.last_seen_at}Z`).getTime() < 5 * 60000);
              return (
              <dl key={d.id} className="facts">
                <dt>{d.id}</dt>
                <dd><Status value={live ? "HEALTHY" : "AT_RISK"} label={live ? "online" : "offline"} /></dd>
                <dt>Last seen</dt><dd>{d.last_seen_at ? when(d.last_seen_at) : "never"}</dd>
                <dt>Firmware</dt><dd>{d.firmware}</dd>
              </dl>
              );
            })}
          </section>

          <section className="panel">
            <h2>Interventions</h2>
            {!mine.length && <p className="muted">None. Run "Find merchants who need attention" from Merchants to draft one if this merchant is flagged.</p>}
            {mine.map((i) => (
              <div key={i.id} style={{ marginBottom: 12 }}>
                <Status value={i.status} /> <b className="small">{CHANNEL_LABEL[i.channel]}</b>
                <div className="small">{i.title}</div>
                <div className="muted small">{i.decided_by ? `${i.decided_by}, ${when(i.decided_at!)}` : `Drafted ${when(i.created_at)}`}</div>
              </div>
            ))}
            {mine.some((i) => i.status === "PENDING_APPROVAL") && <Link href="/approvals" className="small">Open approvals</Link>}
          </section>

          <section className="panel">
            <h2>Payment disputes</h2>
            {!myCases.length && <p className="muted">No disputes raised from this terminal.</p>}
            {myCases.map((c) => (
              <div key={c.id} style={{ marginBottom: 10 }}>
                <Status value={c.status} /> <b className="small">{CASE_LABEL[c.type]}</b>
                <div className="small">{pkr(c.claimed_amount_rupees)}, {when(c.opened_at)}</div>
              </div>
            ))}
          </section>
        </aside>
      </div>
    </>
  );
}

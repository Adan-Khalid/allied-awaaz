"use client";

import { useEffect, useState } from "react";
import Trace from "@/components/Trace";
import { ErrorNote } from "@/components/ui";
import { api, type AgentRun } from "@/lib/api";
import { OUTCOME_LABEL, usePoll, when } from "@/lib/format";

export default function Activity() {
  const [agent, setAgent] = useState<"all" | "merchant" | "activation">("all");
  const { data, error } = usePoll(() => api<AgentRun[]>("/v1/console/agent-runs?limit=100"), 4000);
  const runs = (data ?? []).filter((r) => agent === "all" || r.agent === agent);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (runs.length && !runs.some((r) => r.id === selected)) setSelected(runs[0].id);
  }, [runs, selected]);

  const run = runs.find((r) => r.id === selected) ?? null;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Agent activity</h1>
          <p>Every decision either agent made, step by step: what it heard, what it planned, which approved tools it called, and how it checked the result before answering.</p>
        </div>
      </div>
      <ErrorNote error={error} />
      <div className="tabs" role="tablist">
        {(["all", "merchant", "activation"] as const).map((a) => (
          <button key={a} role="tab" aria-selected={agent === a} onClick={() => setAgent(a)}>
            {a === "all" ? "All" : a === "merchant" ? "Terminal agent" : "Activation agent"}
          </button>
        ))}
      </div>
      {data && !runs.length && <div className="empty panel">No runs yet. Use a terminal, or run an activation sweep from Merchants.</div>}
      {runs.length > 0 && (
        <div className="grid2" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(0, 3fr)" }}>
          <div className="panel runlist" role="tablist" aria-label="Runs" style={{ padding: 8 }}>
            {runs.map((r) => (
              <button key={r.id} role="tab" aria-selected={r.id === selected} onClick={() => setSelected(r.id)}>
                <b className="small">{OUTCOME_LABEL[r.outcome ?? ""] ?? r.outcome}</b>
                <span>
                  {r.agent === "merchant" ? (r.input_text ? `"${r.input_text.slice(0, 48)}"` : "Keypad") : r.input_text}
                  {", "}{when(r.created_at)}
                </span>
              </button>
            ))}
          </div>
          <section className="panel">{run && <Trace run={run} />}</section>
        </div>
      )}
    </>
  );
}

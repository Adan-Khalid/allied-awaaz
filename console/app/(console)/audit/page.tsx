"use client";

import { ErrorNote } from "@/components/ui";
import { api, type AuditEntry } from "@/lib/api";
import { clock, usePoll } from "@/lib/format";

function actor(a: string) {
  const [kind, id] = a.split(/:(.*)/s);
  const label: Record<string, string> = { device: "Terminal", staff: "Staff", agent: "Agent run", gateway: "Payment gateway" };
  return label[kind] ? <>{label[kind]} <span className="muted">{id}</span></> : a;
}

export default function Audit() {
  const { data, error } = usePoll(() => api<AuditEntry[]>("/v1/console/audit?limit=300"), 5000);
  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Audit log</h1>
          <p>Append-only record of every payment state change, agent run and staff decision, newest first.</p>
        </div>
      </div>
      <ErrorNote error={error} />
      {data && (
        <div className="tablewrap">
          <table>
            <thead><tr><th>Time</th><th>Who</th><th>Action</th><th>Subject</th><th>Details</th></tr></thead>
            <tbody>
              {data.map((a, i) => (
                <tr key={`${a.at}-${i}`}>
                  <td style={{ whiteSpace: "nowrap" }}>{clock(a.at)}</td>
                  <td>{actor(a.actor)}</td>
                  <td><b className="small">{a.action}</b></td>
                  <td className="muted small">{a.subject}</td>
                  <td className="small"><code style={{ overflowWrap: "anywhere" }}>{JSON.stringify(a.detail)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

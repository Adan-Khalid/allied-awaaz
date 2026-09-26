"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { StaffContext } from "@/components/staff";
import { api, ApiError, session, type Staff, type Summary } from "@/lib/api";
import { usePoll } from "@/lib/format";

const NAV = [
  { href: "/merchants", label: "Merchants" },
  { href: "/approvals", label: "Approvals", badge: "pending_approvals" as const },
  { href: "/exceptions", label: "Payment disputes", badge: "open_exceptions" as const },
  { href: "/activity", label: "Agent activity" },
  { href: "/audit", label: "Audit log" },
];

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [staff, setStaff] = useState<Staff | null>(null);
  const [offline, setOffline] = useState<string | null>(null);
  const { data: summary } = usePoll(
    () => (session.get() ? api<Summary>("/v1/console/summary") : Promise.resolve(null)), 6000, [staff?.name]);

  useEffect(() => {
    if (!session.get()) { router.replace("/login"); return; }
    let cancelled = false;
    // Only a 401 ends the session. Network blips (a request cut off by navigation, backend restarting)
    // retry instead of silently signing the user out.
    const check = async (attempt: number): Promise<void> => {
      try {
        const s = await api<Staff>("/v1/console/whoami");
        if (!cancelled) { setStaff(s); setOffline(null); }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 401) { session.clear(); router.replace("/login"); return; }
        setOffline((e as Error).message);
        window.setTimeout(() => check(attempt + 1), Math.min(1000 * 2 ** attempt, 8000));
      }
    };
    check(0);
    return () => { cancelled = true; };
  }, [router]);

  if (!staff) {
    return offline ? <main className="login"><div className="notice error" role="alert">{offline} Retrying...</div></main> : null;
  }

  return (
    <StaffContext.Provider value={staff}>
      <div className="shell">
        <aside className="rail">
          <div className="brand">Allied Awaaz<small>Relationship console</small></div>
          <nav className="nav" aria-label="Console">
            {NAV.map((n) => {
              const count = n.badge && summary ? summary[n.badge] : 0;
              return (
                <Link key={n.href} href={n.href} aria-current={path.startsWith(n.href) ? "page" : undefined}>
                  {n.label}
                  {count > 0 && <span className="count" aria-label={`${count} waiting`}>{count}</span>}
                </Link>
              );
            })}
          </nav>
          <div className="who">
            <strong>{staff.name}</strong>
            {staff.role === "supervisor" ? "Supervisor" : "Relationship manager"}
            <br />
            <button onClick={() => { session.clear(); router.replace("/login"); }}>Sign out</button>
          </div>
        </aside>
        <main className="main">{children}</main>
      </div>
    </StaffContext.Provider>
  );
}

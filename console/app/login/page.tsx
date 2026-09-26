"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError, session, type Staff } from "@/lib/api";

export default function Login() {
  const router = useRouter();
  const [ready, setReady] = useState(false);  // blocks native form submits before hydration (would put the token in the URL)
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => setReady(true), []);

  async function signIn(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // Uncontrolled input: anything typed or autofilled before hydration is kept.
    const token = String(new FormData(e.currentTarget).get("token") ?? "").trim();
    if (!token) { setError("Enter your staff token."); return; }
    setBusy(true);
    setError(null);
    try {
      await api<Staff>("/v1/console/whoami", { token });
      session.set(token);
      router.replace("/merchants");
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "That staff token isn't recognised." : (err as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form onSubmit={signIn} method="post" noValidate>
        <h1>Allied Awaaz</h1>
        <p>Merchant activation and payment exceptions for relationship teams.</p>
        <label htmlFor="token">Staff token</label>
        <input id="token" name="token" className="text" type="password" autoComplete="off" autoFocus />
        {error && <div className="notice error" role="alert">{error}</div>}
        <button className="btn primary" disabled={!ready || busy}>{busy ? "Signing in..." : "Sign in"}</button>
        <span className="muted small">Demo tokens: dev-rm-token (RM), dev-sup-token (supervisor).</span>
      </form>
    </main>
  );
}

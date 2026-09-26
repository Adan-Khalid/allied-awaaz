# Allied Awaaz console

Bank-side console for relationship managers and supervisors. Next.js 15 (App Router), React 19,
TypeScript, no UI framework. Talks to the backend's `/v1/console/*` API with a staff bearer token.

## Screens

| Screen | Job |
|--------|-----|
| Merchants | Health table sorted at-risk first, summary strip, and "Find merchants who need attention" (runs the activation agent) |
| Merchant detail | Why the score is what it is, ledger signals, every terminal-agent run with its step-by-step reasoning, payments, terminals, interventions, disputes |
| Approvals | Agent drafts with evidence and full reasoning. Approve or reject with a note. WhatsApp messages to merchants are supervisor-only (enforced by the backend, explained in the UI) |
| Payment disputes | Cases raised by terminals, with what happened and the agent's reasoning for each |
| Agent activity | Every run from both agents, filterable |
| Audit log | Append-only record of payments, agent runs and staff decisions |

Everything polls every 4 to 8 seconds, so cases raised at the terminal during the live demo appear
without a refresh.

## Run

```bash
cp .env.example .env.local        # NEXT_PUBLIC_API_BASE, default http://localhost:8000
npm install
npm run dev                       # http://localhost:3000
```
Backend must allow this origin: `AWAAZ_CORS_ORIGINS=http://localhost:3000`.

Sign in with a staff token from `AWAAZ_STAFF_TOKENS`. Demo defaults: `dev-rm-token` (RM) and
`dev-sup-token` (supervisor). Use one browser window per role to show the approval gate.

Production build: `npm run build && npm start`.

## Notes

* The token lives in `sessionStorage` for the demo. A pilot replaces this with ABL SSO and
  short-lived tokens issued by the bank's identity provider.
* Fonts load from Google Fonts with system fallbacks, so the console still renders offline.

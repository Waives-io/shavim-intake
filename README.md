# shavim-intake — קליטת מתמודד חדש (עמותת שווים)

Single-page app + API served by one Cloudflare Worker (static assets from `dist/`, `/api/*` to `worker/index.mjs`, D1 for data, KV for files) + EmailJS.
Deploy both with `bash scripts/deploy-site.sh`. Its own origin, so no other site shares its storage or saved passwords. The old GitHub Pages address (`gh-pages` branch) only redirects here.

| URL | Who |
|---|---|
| https://shavim-intake.autumn-glitter-1f91.workers.dev/ | Referrer form (general link Noa shares) |
| `/?r=<token>` | Referrer's personal continuation link |
| `/?noa` | Noa's dashboard (password, Bearer session 30 days) |
| `/api/*` | API (Cloudflare account contact@waives.io) |

- `index.html` — whole app. Config block at the top (`SHAVIM_CONFIG`). Empty `apiUrl` ⇒ demo mode (localStorage + IndexedDB).
- `worker/index.mjs` — API. Referrers act only through a secret 64-hex token; staff through `Authorization: Bearer`. Daily cron (02:15 UTC) purges KV files 14 days after an approved request was fully downloaded.
- `migrations/` — D1 schema (`npx wrangler d1 migrations apply shavim-intake --remote`).
- `wrangler.jsonc` — bindings `DB`, `FILES`, cron, vars. Secret: `STAFF_PASSWORD` (`npx wrangler secret put STAFF_PASSWORD`).
- Download to `\\JAACOV\...` uses the File System Access API (Chrome/Edge); the chosen folder handle is kept in IndexedDB.

Security model:
- A new form never reopens an existing request by ID/email (that would leak its token); every same-ID request is flagged `possible_duplicate`.
- An approved request's link returns only `{status:'approved'}`; no uploads or edits after approval; approval never reverts.
- Uploads: allow-listed extensions, magic-byte sniffing, 15 MB, max 20 files per request. KV write is rolled back if the D1 insert fails.
- Limits: 10 new requests/hour per IP, 200/day overall; login 5 failures/15 min per IP and 30 overall.
- Server-owned rules for retention: ISO timestamps only, `fully_downloaded_at` and purge only when every file is downloaded.
- Not yet: CAPTCHA (Turnstile) on the form.

Tests:
- `python -m http.server 8765` then `python test/qa.py` — UI in demo mode (44 checks).
- `npx wrangler d1 migrations apply shavim-intake --local`, `npx wrangler dev --local --port 8787` (password from `.dev.vars`), `node test/api.mjs` — API (35 checks).
- `python test/live_smoke.py [API] [PASSWORD]` — the real page against a Worker (page served from 127.0.0.1:8765).

Setup steps (Hebrew): `SETUP-GUIDE.md`.

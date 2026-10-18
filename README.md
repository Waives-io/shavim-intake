# shavim-intake — קליטת מתמודד חדש (עמותת שווים)

Static single-page app (GitHub Pages) + Supabase (Postgres, Auth, private Storage) + EmailJS.

| URL | Who |
|---|---|
| `/` | Referrer form (general link Noa shares) |
| `/?r=<token>` | Referrer's personal continuation link |
| `/?noa` | Noa's dashboard (Supabase Auth, staff table) |

- `index.html` — whole app. Config block at the top (`SHAVIM_CONFIG`). Empty `supabaseUrl` ⇒ demo mode (localStorage + IndexedDB).
- `supabase/setup.sql` — tables, RLS, token-scoped RPCs for anonymous referrers, private bucket `intake` + storage policies. Idempotent.
- Download to `\\JAACOV\...` uses the File System Access API (Chrome/Edge); the chosen folder handle is kept in IndexedDB.
- `.github/workflows/keepalive.yml` + `scripts/daily.mjs` — daily job with the service role key (GitHub secrets `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`): `rpc/ping` so the free project never pauses, purges approved requests 14 days after full download (paginated, verified empty before `purged_at`), and deletes objects queued in `public.trash` by referrer removals.

Security model: anonymous users never read tables. They act only through `intake_*` RPCs with the secret request token, and can only INSERT objects at `<token>/<name>.<allowed ext>` for open requests (max 20 per request). Staff = emails in `public.staff` (signups disabled).
- A new form never reopens an existing request by ID/email (that would leak its token); same-ID requests are all flagged `possible_duplicate`.
- `intake_get` on an approved request returns only `{status:'approved'}`.
- `intake_add_file` takes size/MIME from `storage.objects.metadata`, not from the caller; the download extension comes from the stored path.
- Server checks the ID check digit (`_tz_ok`). `ping()` is service-role only.
- Not yet: CAPTCHA / rate limit on creating requests (planned).

Setup steps (Hebrew): `SETUP-GUIDE.md`.

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
- `.github/workflows/keepalive.yml` — daily `rpc/ping` so the free Supabase project never pauses.

Security model: anonymous users never read tables. They act only through `intake_*` RPCs with the secret request token, and can only INSERT objects under `<token>/` for open requests. Staff = emails in `public.staff` (signups disabled).

Setup steps (Hebrew): `SETUP-GUIDE.md`.

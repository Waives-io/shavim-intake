// Security checks for supabase/setup.sql on an in-process Postgres (PGlite).
// One-time: npm i --no-save @electric-sql/pglite@0.2.17   Run: node test/sql/security.mjs
import { PGlite } from '@electric-sql/pglite';
import fs from 'fs';
const setup = fs.readFileSync(process.argv[2] || new URL('../../supabase/setup.sql', import.meta.url), 'utf8').replace('create extension if not exists pgcrypto;', '-- pgcrypto: built into Supabase');
const db = new PGlite();
await db.exec(fs.readFileSync(new URL('./supabase_stub.sql', import.meta.url), 'utf8'));
await db.exec(setup);
await db.exec(setup);           // idempotent: second run must succeed too
console.log('setup.sql ran twice OK');

let pass = 0, fail = 0;
const one = async sql => (await db.query(sql)).rows[0];
async function t(name, sql, expect) {
  let got;
  try { const r = await one(sql); got = r ? Object.values(r)[0] : 'ok'; }
  catch (e) { got = 'ERR ' + e.message; }
  const ok = typeof expect === 'function' ? expect(got) : String(got) === String(expect);
  ok ? pass++ : fail++;
  console.log((ok ? 'PASS ' : 'FAIL ') + name + ' → ' + (typeof got === 'object' ? JSON.stringify(got) : got));
}
const denied = g => String(g).includes('permission denied');
const rls = g => String(g).includes('row-level security');
const P = `'{"participant_name":"דנה כהן","participant_id":"034567891","ref_name":"שירה","ref_email":"shira@x.co.il","ref_phone":"052-1234567"}'::jsonb`;

await db.query(`select set_config('t.v', (public.intake_save(null, ${P}))->>'token', false)`);
const V = `current_setting('t.v')`;
await db.exec('set role anon');
await t('same ID+email → new token, not the victim\'s', `select ((public.intake_save(null, ${P}))->>'token') <> ${V}`, true);
await t('merge reply hides victim files', `select jsonb_array_length((public.intake_save(null, ${P}))->'files')`, 0);
await t('anon cannot read requests', 'select count(*) from public.requests', denied);
await t('anon cannot read files', 'select count(*) from public.files', denied);
await t('anon cannot read staff', 'select count(*) from public.staff', denied);
await t('anon cannot read trash', 'select count(*) from public.trash', denied);
await t('anon cannot update requests', `update public.requests set status='approved'`, denied);
await t('bad ID check digit rejected', `select public.intake_save(null, jsonb_set(${P}, '{participant_id}', '"034567892"'))`, g => String(g).includes('bad_participant_id'));
await t('ping blocked for anon', 'select public.ping()', denied);
await t('storage: good path allowed', `insert into storage.objects(bucket_id,name,metadata) values ('intake', ${V}||'/committee_1_ab.pdf', '{"size":123,"mimetype":"application/pdf"}')`, 'ok');
await t('storage: nested path rejected', `insert into storage.objects(bucket_id,name) values ('intake', ${V}||'/hidden/a.pdf')`, rls);
await t('storage: .exe rejected', `insert into storage.objects(bucket_id,name) values ('intake', ${V}||'/x.exe')`, rls);
await t('storage: unknown token rejected', `insert into storage.objects(bucket_id,name) values ('intake', gen_random_uuid()||'/x.pdf')`, rls);
await t('register: size from storage, not caller', `select public.intake_add_file(${V}::uuid,'committee',${V}||'/committee_1_ab.pdf','evil.exe',999999,'text/x')->'files'->0->>'size_bytes'`, 123);
await t('register: path of another token rejected', `select public.intake_add_file(${V}::uuid,'committee',gen_random_uuid()||'/a.pdf','a.pdf',1,'application/pdf')`, g => String(g).includes('bad_path'));
for (let i = 2; i <= 20; i++) await db.query(`insert into storage.objects(bucket_id,name) values ('intake', ${V}||'/f_${i}.pdf')`);
await t('storage: 21st object rejected (cap 20)', `insert into storage.objects(bucket_id,name) values ('intake', ${V}||'/f_21.pdf')`, rls);
await t('remove file works', `select jsonb_array_length(public.intake_remove_file(${V}::uuid, (public.intake_get(${V}::uuid)->'files'->0->>'id')::uuid)->'files')`, 0);
await db.exec('reset role');
await t('removed file queued in trash', 'select count(*) from public.trash', 1);
await db.query(`update public.requests set status='approved' where token=${V}::uuid`);
await db.exec('set role anon');
await t('approved link: no personal details', `select public.intake_get(${V}::uuid)`, g => JSON.stringify(g) === '{"status":"approved"}');
await t('approved link: cannot upload', `insert into storage.objects(bucket_id,name) values ('intake', ${V}||'/late.pdf')`, rls);
await db.exec('reset role');
await t('all same-ID requests flagged', `select count(*) from public.requests where participant_id='034567891' and possible_duplicate`, 3);
await db.exec('set role authenticated');
await db.query(`select set_config('request.jwt.claims','{"email":"noa@amutatshavim.co.il"}',false)`);
await t('Noa sees all requests', 'select count(*) from public.requests', 3);
await t('Noa cannot read trash', 'select count(*) from public.trash', denied);
await db.query(`select set_config('request.jwt.claims','{"email":"stranger@x.com"}',false)`);
await t('logged-in stranger sees nothing', 'select count(*) from public.requests', 0);
await t('logged-in stranger cannot add self to staff', `insert into public.staff values ('stranger@x.com')`, g => String(g).includes('row-level security') || denied(g));
await db.exec('reset role');
await db.exec('set role service_role');
await t('ping works for service role', 'select public.ping()', 'ok');
console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);

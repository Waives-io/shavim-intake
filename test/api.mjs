// API checks for worker/index.mjs against a local Worker.
//   1. npx wrangler d1 migrations apply shavim-intake --local   (fresh run: delete .wrangler/state first)
//   2. npx wrangler dev --local --port 8787        (STAFF_PASSWORD comes from .dev.vars)
//   3. node test/api.mjs
import fs from 'fs';
const BASE = process.env.API || 'http://127.0.0.1:8787';
const PASS = (fs.readFileSync(new URL('../.dev.vars', import.meta.url), 'utf8').match(/^STAFF_PASSWORD=(.*)$/m) || [])[1]?.trim();
const EMAIL = 'shavim.holon@gmail.com';

let pass = 0, fail = 0;
const check = (name, ok, extra = '') => { ok ? pass++ : fail++; console.log((ok ? 'PASS ' : 'FAIL ') + name + (extra ? ' — ' + extra : '')); };
async function api(path, {method = 'GET', json, body, auth} = {}) {
  const headers = {};
  if (json !== undefined) headers['Content-Type'] = 'application/json';
  if (auth) headers.Authorization = 'Bearer ' + auth;
  const res = await fetch(BASE + path, {method, headers, body: json !== undefined ? JSON.stringify(json) : body});
  const type = res.headers.get('content-type') || '';
  return {status: res.status, headers: res.headers, data: type.includes('json') ? await res.json() : new Uint8Array(await res.arrayBuffer())};
}
const PDF = new TextEncoder().encode('%PDF-1.4 test document');
function upload(token, doc, bytes, name, replace) {
  const fd = new FormData(); fd.append('doc_type', doc); fd.append('file', new Blob([bytes]), name); if (replace) fd.append('replace', '1');
  return api(`/api/intake/${token}/files`, {method: 'POST', body: fd});
}
const D = {participant_name: 'דנה כהן', participant_id: '034567891', ref_name: 'שירה אדלר', ref_email: 'shira@example.co.il', ref_phone: '052-1234567'};

// ---------- referrer ----------
let r = await api('/api/intake', {method: 'POST', json: {token: null, turnstile: 'XXXX.DUMMY.TOKEN.XXXX', details: D}});
check('create request', r.status === 201 && /^[a-f0-9]{64}$/.test(r.data.token), r.status);
const T = r.data.token;
r = await api('/api/intake', {method: 'POST', json: {token: null, turnstile: 'XXXX.DUMMY.TOKEN.XXXX', details: D}});
check('same ID + email → NEW token (never the existing one)', r.status === 201 && r.data.token !== T && !r.data.merged);
const T2 = r.data.token;
check('reply to a stranger carries no files of the other request', Array.isArray(r.data.files) && r.data.files.length === 0);
r = await api('/api/intake', {method: 'POST', json: {token: null, details: D}});
check('new request without the human check → 403', r.status === 403 && r.data.error === 'captcha_failed', JSON.stringify(r.data));
r = await api('/api/intake', {method: 'POST', json: {token: null, turnstile: 'XXXX.DUMMY.TOKEN.XXXX', details: {...D, participant_id: '034567892'}}});
check('bad ID check digit → 400', r.status === 400 && r.data.error === 'bad_participant_id', JSON.stringify(r.data));
r = await api('/api/intake', {method: 'POST', json: {token: null, turnstile: 'XXXX.DUMMY.TOKEN.XXXX', details: {...D, ref_phone: '03-1234567'}}});
check('bad phone → 400', r.status === 400);
r = await upload(T, 'committee', new TextEncoder().encode('not a pdf'), 'fake.pdf');
check('fake PDF → 415', r.status === 415);
r = await upload(T, 'committee', new Uint8Array([0x4d, 0x5a]), 'virus.exe');
check('.exe → 415', r.status === 415);
r = await upload(T, 'nonsense', PDF, 'a.pdf');
check('bad doc_type → 400', r.status === 400);
r = await upload(T, 'committee', PDF, 'ועדה.pdf');
check('upload real PDF', r.status === 201 && r.data.files.length === 1 && r.data.files[0].original_name === 'ועדה.pdf');
r = await api(`/api/intake/${T}/submit`, {method: 'POST'});
check('submit blocked while required docs missing → 409', r.status === 409 && r.data.error === 'missing_required');
await upload(T, 'psychiatric', PDF, 'psych.pdf');
r = await upload(T, 'psychiatric', PDF, 'psych-v2.pdf', true);
const ps = r.data.files.filter(f => f.doc_type === 'psychiatric');
check('"replace" upload marks the earlier file replaced', ps.length === 2 && ps.find(f => f.original_name === 'psych.pdf').replaced && !ps.find(f => f.original_name === 'psych-v2.pdf').replaced);
r = await upload(T, 'idcard', PDF, 'tz.pdf');
const idcard = r.data.files.find(f => f.doc_type === 'idcard').id;
r = await api(`/api/intake/${T}/files/${idcard}`, {method: 'DELETE'});
check('referrer removes a file', r.status === 200 && !r.data.files.some(f => f.id === idcard));
await upload(T, 'social', PDF, 'social.pdf');
r = await api(`/api/intake/${T}/submit`, {method: 'POST'});
check('submit with all required', r.status === 200 && r.data.status === 'submitted');
r = await api(`/api/intake/${'0'.repeat(64)}`);
check('unknown token → 404', r.status === 404);

// ---------- staff ----------
r = await api('/api/staff/requests');
check('staff list without login → 401', r.status === 401);
r = await api('/api/staff/login', {method: 'POST', json: {email: EMAIL, password: PASS + 'x'}});
check('wrong password → 401', r.status === 401);
r = await api('/api/staff/login', {method: 'POST', json: {email: EMAIL.toUpperCase(), password: PASS}});
check('login', r.status === 200 && /^[a-f0-9]{64}$/.test(r.data.token));
const S = r.data.token;
r = await api('/api/staff/requests', {auth: S});
const mine = r.data.find(x => x.token === T), other = r.data.find(x => x.token === T2);
check('list shows both same-ID requests flagged', mine && other && mine.possible_duplicate && other.possible_duplicate);
const fid = mine.files.find(f => f.doc_type === 'committee').id;
r = await api(`/api/staff/files/${fid}`, {auth: S});
check('staff gets file bytes', r.status === 200 && new TextDecoder().decode(r.data).startsWith('%PDF'));
r = await api('/api/staff/files', {method: 'PATCH', auth: S, json: {ids: mine.files.map(f => f.id), downloaded_at: new Date().toISOString()}});
check('mark downloaded', r.status === 200);
r = await api(`/api/intake/${T}/files/${fid}`, {method: 'DELETE'});
const still = (await api(`/api/intake/${T}`)).data.files.some(f => f.id === fid);
check('referrer cannot remove a downloaded file', still);
r = await api(`/api/staff/requests/${mine.id}`, {method: 'PATCH', auth: S, json: {participant_name: 'x'}});
check('staff patch rejects non-whitelisted field', r.status === 400);
r = await api(`/api/staff/requests/${mine.id}`, {method: 'PATCH', auth: S, json: {status: 'approved', approved_at: new Date().toISOString()}});
check('approve', r.status === 200);
r = await api(`/api/intake/${T}`);
check('approved link returns no personal details', r.status === 200 && JSON.stringify(r.data) === '{"status":"approved"}', JSON.stringify(r.data));
r = await upload(T, 'medical', PDF, 'late.pdf');
check('no upload after approval → 409', r.status === 409);
r = await api(`/api/staff/requests/${mine.id}`, {method: 'PATCH', auth: S, json: {status: 'submitted'}});
check('approved request cannot be reopened → 409', r.status === 409);
r = await api(`/api/staff/requests/${mine.id}`, {method: 'PATCH', auth: S, json: {last_download_at: '12/31/2099'}});
check('non-ISO date rejected → 400', r.status === 400);
r = await api(`/api/staff/requests/${mine.id}/purge`, {method: 'POST', auth: S});
check('purge before full download → 409', r.status === 409);
r = await api(`/api/staff/requests/${other.id}`, {method: 'PATCH', auth: S, json: {archived_at: new Date().toISOString()}});
check('only approved requests can be archived → 409', r.status === 409);
r = await api(`/api/staff/requests/${mine.id}`, {method: 'PATCH', auth: S, json: {archived_at: new Date().toISOString(), fully_downloaded_at: new Date().toISOString()}});
check('archive + full download on approved', r.status === 200);
r = await api(`/api/staff/requests/${mine.id}/purge`, {method: 'POST', auth: S});
r = await api(`/api/staff/files/${fid}`, {auth: S});
check('purged file → 410', r.status === 410);
r = await api(`/api/staff/requests/${other.id}`, {method: 'DELETE', auth: S});
check('delete request', r.status === 200 && !(await api('/api/staff/requests', {auth: S})).data.some(x => x.id === other.id));
// per-document review
r = await api('/api/intake', {method: 'POST', json: {token: null, turnstile: 'XXXX.DUMMY.TOKEN.XXXX', details: {...D, participant_id: '201234564'}}});
const T3 = r.data.token;
for (const d of ['committee', 'psychiatric', 'social']) await upload(T3, d, PDF, d + '.pdf');
await api(`/api/intake/${T3}/submit`, {method: 'POST'});
const R3 = (await api('/api/staff/requests', {auth: S})).data.find(x => x.token === T3);
r = await api(`/api/staff/requests/${R3.id}/docs/medical`, {method: 'PUT', auth: S, json: {state: 'ok'}});
check('review of a document with no file → 409', r.status === 409);
r = await api(`/api/staff/requests/${R3.id}/docs/psychiatric`, {method: 'PUT', auth: S, json: {state: 'replace'}});
check('mark a document "replace"', r.status === 200 && r.data.reviews.psychiatric === 'replace' && !r.data.approved);
r = await api(`/api/intake/${T3}`);
check('referrer sees which document to replace', r.data.reviews && r.data.reviews.psychiatric === 'replace');
r = await upload(T3, 'psychiatric', PDF, 'psych-new.pdf');
check('replacement upload → document "check" (לבדיקה)', r.status === 201 && r.data.reviews.psychiatric === 'check');
const psy = r.data.files.filter(f => f.doc_type === 'psychiatric');
check('old file marked replaced, new one current', psy.length === 2 && psy.filter(f => f.replaced).length === 1 && psy.find(f => !f.replaced).original_name === 'psych-new.pdf');
await api(`/api/staff/requests/${R3.id}/docs/committee`, {method: 'PUT', auth: S, json: {state: 'ok'}});
await api(`/api/staff/requests/${R3.id}/docs/psychiatric`, {method: 'PUT', auth: S, json: {state: 'ok'}});
r = await api(`/api/staff/requests/${R3.id}/docs/social`, {method: 'PUT', auth: S, json: {state: 'ok'}});
check('all required "ok" → request approved', r.status === 200 && r.data.approved === true);
r = await api(`/api/intake/${T3}`);
check('…and the link is closed', JSON.stringify(r.data) === '{"status":"approved"}');
r = await api(`/api/staff/requests/${R3.id}/docs/social`, {method: 'PUT', auth: S, json: {state: null}});
check('no review changes after approval → 409', r.status === 409);
await api(`/api/staff/requests/${R3.id}`, {method: 'DELETE', auth: S});

// change password from inside the dashboard
const S2 = (await api('/api/staff/login', {method: 'POST', json: {email: EMAIL, password: PASS}})).data.token;
const NEWPASS = PASS + '-new';
r = await api('/api/staff/password', {method: 'POST', auth: S, json: {current: 'wrong', next: NEWPASS}});
check('change password with a wrong current password → 403', r.status === 403);
r = await api('/api/staff/password', {method: 'POST', auth: S, json: {current: PASS, next: 'short'}});
check('new password under 8 characters → 400', r.status === 400);
r = await api('/api/staff/password', {method: 'POST', auth: S, json: {current: PASS, next: NEWPASS}});
check('change password', r.status === 200);
check('other computers are logged out', (await api('/api/staff/requests', {auth: S2})).status === 401);
check('this computer stays logged in', (await api('/api/staff/requests', {auth: S})).status === 200);
check('old password no longer works', (await api('/api/staff/login', {method: 'POST', json: {email: EMAIL, password: PASS}})).status === 401);
check('new password works', (await api('/api/staff/login', {method: 'POST', json: {email: EMAIL, password: NEWPASS}})).status === 200);
await api('/api/staff/password', {method: 'POST', auth: S, json: {current: NEWPASS, next: PASS}});   // back, so the test can run again

r = await api('/api/staff/logout', {method: 'POST', auth: S});
r = await api('/api/staff/requests', {auth: S});
check('logout kills the session', r.status === 401);
for (let i = 0; i < 5; i++) await api('/api/staff/login', {method: 'POST', json: {email: EMAIL, password: 'wrong'}});
r = await api('/api/staff/login', {method: 'POST', json: {email: EMAIL, password: PASS}});
check('6th login after 5 failures → 429', r.status === 429);
let last;
for (let i = 0; i < 10; i++) last = await api('/api/intake', {method: 'POST', json: {token: null, turnstile: 'XXXX.DUMMY.TOKEN.XXXX', details: D}});
check('11th+ new request from one address in an hour → 429', last.status === 429, String(last.status));
r = await fetch(BASE + '/api/intake', {method: 'OPTIONS'});
check('CORS preflight', r.status === 204 && r.headers.get('access-control-allow-origin') === '*');

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);

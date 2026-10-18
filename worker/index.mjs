// עמותת שווים · קליטת מתמודד חדש · API (Cloudflare Worker + D1 + KV)
//
// Referrer (anonymous) — only through the secret request token:
//   POST   /api/intake                      {token|null, details}  create / update details
//   GET    /api/intake/:token
//   POST   /api/intake/:token/files         multipart: doc_type, file
//   DELETE /api/intake/:token/files/:id     only before Noa downloaded it
//   POST   /api/intake/:token/submit
// Staff (Bearer session token):
//   POST   /api/staff/login                 {email, password}
//   GET    /api/staff/session    POST /api/staff/logout
//   GET    /api/staff/requests
//   PATCH  /api/staff/requests/:id          whitelisted fields
//   DELETE /api/staff/requests/:id
//   POST   /api/staff/requests/:id/purge
//   PATCH  /api/staff/files                 {ids, downloaded_at}
//   GET    /api/staff/files/:id             the file itself

const DOC_TYPES = ['committee', 'psychiatric', 'social', 'medical', 'idcard'];
const REQUIRED = ['committee', 'psychiatric', 'social'];
const MAX_BYTES = 15 * 1024 * 1024;
const MAX_FILES_PER_REQUEST = 20;
const SESSION_DAYS = 30;
const LOGIN_LIMIT = 5, LOGIN_WINDOW_MIN = 15, LOGIN_GLOBAL_LIMIT = 30;   // failures per 15 min: per IP / all IPs
const CREATE_PER_IP_HOUR = 10, CREATE_PER_DAY = 200;                      // new requests from the anonymous form
const EXT_MIME = {pdf:'application/pdf', jpg:'image/jpeg', jpeg:'image/jpeg', png:'image/png', webp:'image/webp', heic:'image/heic', heif:'image/heif',
  doc:'application/msword', docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'};
const STAFF_FIELDS = ['status', 'approved_at', 'thanks_sent_at', 'last_reminder_at', 'folder_name', 'last_download_at', 'fully_downloaded_at', 'archived_at'];
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$/;   // canonical timestamps only (cleanup compares text)

class HttpError extends Error { constructor(status, code) { super(code); this.status = status; this.code = code; } }
const must = (cond, code, status = 400) => { if (!cond) throw new HttpError(status, code); };
const now = () => new Date().toISOString();
const uid = () => crypto.randomUUID();
const randomToken = () => Array.from(crypto.getRandomValues(new Uint8Array(32)), b => b.toString(16).padStart(2, '0')).join('');
async function sha256(s) { const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)); return Array.from(new Uint8Array(d), b => b.toString(16).padStart(2, '0')).join(''); }
// compares fixed-length digests, so timing does not depend on the input
async function sameSecret(a, b) { return safeEqual(await sha256(String(a)), await sha256(String(b))); }
function safeEqual(a, b) { a = String(a); b = String(b); let diff = a.length ^ b.length; for (let i = 0; i < Math.max(a.length, b.length); i++) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0); return diff === 0; }

const CORS = {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET,POST,PATCH,DELETE,OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type,Authorization', 'Access-Control-Max-Age': '86400'};
const json = (body, status = 200) => new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', ...CORS}});
async function readJson(req) { must(Number(req.headers.get('content-length') || 0) <= 100000, 'too_large', 413); try { return await req.json(); } catch { throw new HttpError(400, 'invalid_json'); } }

const q = (db, sql, ...a) => db.prepare(sql).bind(...a);
const ipOf = req => req.headers.get('cf-connecting-ip') || 'local';
const one = (db, sql, ...a) => q(db, sql, ...a).first();
const all = async (db, sql, ...a) => (await q(db, sql, ...a).all()).results;

/* ---------- validation (same rules as the form) ---------- */
function tzOk(d) { if (!/^\d{9}$/.test(d)) return false; let s = 0; for (let i = 0; i < 9; i++) { const n = +d[i] * (i % 2 + 1); s += n > 9 ? n - 9 : n; } return s % 10 === 0; }
function cleanDetails(p) {
  must(p && typeof p === 'object', 'bad_details');
  const t = v => String(v ?? '').trim().replace(/\s+/g, ' ');
  const d = {participant_name: t(p.participant_name), participant_id: String(p.participant_id ?? '').replace(/\D/g, '').padStart(9, '0'),
    ref_name: t(p.ref_name), ref_email: t(p.ref_email).toLowerCase(), ref_phone: t(p.ref_phone)};
  must(d.participant_name.length >= 2 && d.participant_name.length <= 120, 'bad_participant_name');
  must(tzOk(d.participant_id), 'bad_participant_id');
  must(d.ref_name.length >= 2 && d.ref_name.length <= 120, 'bad_ref_name');
  must(/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(d.ref_email) && d.ref_email.length <= 200, 'bad_ref_email');
  must(/^05\d-\d{7}$/.test(d.ref_phone), 'bad_ref_phone');
  return d;
}
function sniff(bytes, ext) {
  const b = bytes, hex = n => Array.from(b.slice(0, n), x => x.toString(16).padStart(2, '0')).join('');
  if (ext === 'pdf') return hex(4) === '25504446';
  if (ext === 'jpg' || ext === 'jpeg') return hex(3) === 'ffd8ff';
  if (ext === 'png') return hex(8) === '89504e470d0a1a0a';
  if (ext === 'webp') return hex(4) === '52494646';
  if (ext === 'heic' || ext === 'heif') return String.fromCharCode(...b.slice(4, 8)) === 'ftyp';
  if (ext === 'docx') return hex(4) === '504b0304';
  if (ext === 'doc') return hex(8) === 'd0cf11e0a1b11ae1';
  return false;
}

/* ---------- request views ---------- */
async function filesOf(db, requestId) { return all(db, 'SELECT * FROM files WHERE request_id=? ORDER BY uploaded_at', requestId); }
async function publicView(db, r) {
  const files = await filesOf(db, r.id);
  return {token: r.token, participant_name: r.participant_name, participant_id: r.participant_id, ref_name: r.ref_name, ref_email: r.ref_email, ref_phone: r.ref_phone,
    status: r.status, created_at: r.created_at,
    files: files.map(f => ({id: f.id, doc_type: f.doc_type, original_name: f.original_name, size_bytes: f.size_bytes, uploaded_at: f.uploaded_at, locked: !!f.downloaded_at}))};
}
async function byToken(db, token, open = true) {
  must(/^[a-f0-9]{64}$/.test(token), 'not_found', 404);
  const r = await one(db, 'SELECT * FROM requests WHERE token=?', token);
  must(r, 'not_found', 404);
  if (open) must(r.status !== 'approved', 'closed', 409);
  return r;
}

/* ---------- referrer handlers ---------- */
async function intakeSave(env, req) {
  const body = await readJson(req); const d = cleanDetails(body.details); const db = env.DB; const t = now();
  if (body.token) {
    const r = await byToken(db, String(body.token));
    await q(db, 'UPDATE requests SET participant_name=?,participant_id=?,ref_name=?,ref_email=?,ref_phone=?,updated_at=? WHERE id=?',
      d.participant_name, d.participant_id, d.ref_name, d.ref_email, d.ref_phone, t, r.id).run();
    return json({...await publicView(db, await one(db, 'SELECT * FROM requests WHERE id=?', r.id)), merged: false});
  }
  const ip = ipOf(req), hourAgo = new Date(Date.now() - 3600000).toISOString(), dayAgo = new Date(Date.now() - 86400000).toISOString();
  must((await one(db, "SELECT COUNT(*) AS n FROM events WHERE kind='create' AND ip=? AND at>?", ip, hourAgo)).n < CREATE_PER_IP_HOUR, 'too_many_requests', 429);
  must((await one(db, "SELECT COUNT(*) AS n FROM events WHERE kind='create' AND at>?", dayAgo)).n < CREATE_PER_DAY, 'too_many_requests', 429);
  await q(db, "INSERT INTO events(kind,ip,at) VALUES ('create',?,?)", ip, t).run();
  // Always a new request. Never look up or return an existing one by ID/email: that would hand
  // a stranger the other request's token. Noa sees every request with the same ID flagged.
  const flagged = await q(db, 'UPDATE requests SET possible_duplicate=1 WHERE participant_id=?', d.participant_id).run();
  const dup = flagged.meta.changes > 0;
  const id = uid(), token = randomToken();
  await q(db, 'INSERT INTO requests(id,token,participant_name,participant_id,ref_name,ref_email,ref_phone,possible_duplicate,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
    id, token, d.participant_name, d.participant_id, d.ref_name, d.ref_email, d.ref_phone, dup ? 1 : 0, t, t).run();
  return json({...await publicView(db, await one(db, 'SELECT * FROM requests WHERE id=?', id)), merged: false}, 201);
}
async function intakeUpload(env, req, token) {
  const db = env.DB; const r = await byToken(db, token);
  const len = Number(req.headers.get('content-length'));
  must(len > 0, 'length_required', 411);
  must(len <= MAX_BYTES + 200000, 'too_large', 413);
  const n = await one(db, 'SELECT COUNT(*) AS n FROM files WHERE request_id=?', r.id);
  must(n.n < MAX_FILES_PER_REQUEST, 'too_many_files', 409);
  let form; try { form = await req.formData(); } catch { throw new HttpError(400, 'invalid_form'); }
  const docType = String(form.get('doc_type') || ''); const file = form.get('file');
  must(DOC_TYPES.includes(docType), 'bad_doc_type');
  must(file && typeof file === 'object' && typeof file.arrayBuffer === 'function', 'no_file');
  const name = String(file.name || 'file').slice(0, 200);
  const ext = (name.toLowerCase().match(/\.([a-z0-9]+)$/) || [, ''])[1];
  must(EXT_MIME[ext], 'bad_type', 415);
  must(file.size > 0 && file.size <= MAX_BYTES, 'too_large', 413);
  const buf = await file.arrayBuffer();
  must(sniff(new Uint8Array(buf.slice(0, 16)), ext), 'bad_type', 415);
  const id = uid(), key = `f/${r.id}/${id}`, mime = EXT_MIME[ext];
  await env.FILES.put(key, buf, {metadata: {mime, name}});
  try {
    await q(db, 'INSERT INTO files(id,request_id,doc_type,original_name,kv_key,size_bytes,mime,uploaded_at) VALUES (?,?,?,?,?,?,?,?)', id, r.id, docType, name, key, buf.byteLength, mime, now()).run();
  } catch (e) { await env.FILES.delete(key).catch(() => {}); throw e; }   // no orphan document left in KV
  await q(db, 'UPDATE requests SET updated_at=?, fully_downloaded_at=NULL WHERE id=?', now(), r.id).run();
  return json(await publicView(db, await one(db, 'SELECT * FROM requests WHERE id=?', r.id)), 201);
}
async function intakeRemove(env, token, fileId) {
  const db = env.DB; const r = await byToken(db, token);
  const f = await one(db, 'SELECT * FROM files WHERE id=? AND request_id=? AND downloaded_at IS NULL', fileId, r.id);
  // KV first: if that fails the row stays, so the removal can simply be retried
  if (f) { await env.FILES.delete(f.kv_key); await q(db, 'DELETE FROM files WHERE id=?', f.id).run(); }
  await q(db, 'UPDATE requests SET updated_at=? WHERE id=?', now(), r.id).run();
  return json(await publicView(db, r));
}
async function intakeSubmit(env, token) {
  const db = env.DB; const r = await byToken(db, token);
  const have = new Set((await filesOf(db, r.id)).map(f => f.doc_type));
  must(REQUIRED.every(k => have.has(k)), 'missing_required', 409);
  await q(db, "UPDATE requests SET status='submitted', submitted_at=COALESCE(submitted_at, ?), updated_at=? WHERE id=?", now(), now(), r.id).run();
  return json(await publicView(db, await one(db, 'SELECT * FROM requests WHERE id=?', r.id)));
}

/* ---------- staff ---------- */
async function staffLogin(env, req) {
  const db = env.DB; const ip = ipOf(req);
  const since = new Date(Date.now() - LOGIN_WINDOW_MIN * 60000).toISOString();
  const tries = await one(db, 'SELECT COUNT(*) AS n FROM login_attempts WHERE ip=? AND at>?', ip, since);
  must(tries.n < LOGIN_LIMIT, 'too_many_attempts', 429);
  const everyone = await one(db, 'SELECT COUNT(*) AS n FROM login_attempts WHERE at>?', since);
  must(everyone.n < LOGIN_GLOBAL_LIMIT, 'too_many_attempts', 429);
  const body = await readJson(req);
  must(String(body.email || '').length <= 200 && String(body.password || '').length <= 200, 'bad_login', 401);
  const okEmail = String(body.email || '').trim().toLowerCase() === String(env.STAFF_EMAIL).toLowerCase();
  const okPass = !!env.STAFF_PASSWORD && await sameSecret(String(body.password || ''), env.STAFF_PASSWORD);
  if (!okEmail || !okPass) { await q(db, 'INSERT INTO login_attempts(ip,at) VALUES (?,?)', ip, now()).run(); throw new HttpError(401, 'bad_login'); }
  await q(db, 'DELETE FROM login_attempts WHERE ip=?', ip).run();
  const token = randomToken();
  await q(db, 'INSERT INTO sessions(token_hash,email,expires_at) VALUES (?,?,?)', await sha256(token), env.STAFF_EMAIL, new Date(Date.now() + SESSION_DAYS * 86400000).toISOString()).run();
  return json({token, email: env.STAFF_EMAIL});
}
async function staffAuth(env, req) {
  const m = (req.headers.get('authorization') || '').match(/^Bearer ([a-f0-9]{64})$/);
  must(m, 'unauthorized', 401);
  const s = await one(env.DB, 'SELECT * FROM sessions WHERE token_hash=? AND expires_at>?', await sha256(m[1]), now());
  must(s, 'unauthorized', 401);
  return {email: s.email, hash: await sha256(m[1])};
}
async function listRequests(env) {
  const db = env.DB;
  const reqs = await all(db, 'SELECT * FROM requests ORDER BY created_at DESC');
  const files = await all(db, 'SELECT id,request_id,doc_type,original_name,size_bytes,mime,uploaded_at,downloaded_at FROM files ORDER BY uploaded_at');
  const by = {}; files.forEach(f => (by[f.request_id] ||= []).push(f));
  return json(reqs.map(r => ({...r, possible_duplicate: !!r.possible_duplicate, files: by[r.id] || []})));
}
async function patchRequest(env, req, id) {
  const body = await readJson(req); const sets = [], vals = [];
  const r = await one(env.DB, 'SELECT * FROM requests WHERE id=?', id);
  must(r, 'not_found', 404);
  for (const [k, v] of Object.entries(body)) {
    must(STAFF_FIELDS.includes(k), 'bad_field');
    // staff only ever approves a submitted request; an approved one never reopens
    if (k === 'status') must(v === 'approved' && r.status === 'submitted', 'bad_status', 409);
    else if (k === 'folder_name') must(v === null || (typeof v === 'string' && v.length <= 255), 'bad_value');
    else must(v === null || (typeof v === 'string' && ISO.test(v)), 'bad_value');
    if (k === 'archived_at' && v) must(r.status === 'approved', 'not_approved', 409);
    if (k === 'fully_downloaded_at' && v) {
      const left = await one(env.DB, 'SELECT COUNT(*) AS n FROM files WHERE request_id=? AND downloaded_at IS NULL', id);
      must(left.n === 0, 'not_fully_downloaded', 409);
    }
    sets.push(`${k}=?`); vals.push(v);
  }
  must(sets.length, 'nothing_to_update');
  const res = await q(env.DB, `UPDATE requests SET ${sets.join(',')}, updated_at=? WHERE id=?`, ...vals, now(), id).run();
  must(res.meta.changes, 'not_found', 404);
  return json({ok: true});
}
async function purgeRequest(env, id) {
  const r = await one(env.DB, 'SELECT status, fully_downloaded_at FROM requests WHERE id=?', id);
  must(r, 'not_found', 404);
  must(r.status === 'approved' && r.fully_downloaded_at, 'not_ready_to_purge', 409);   // never before Noa has every file
  const files = await all(env.DB, 'SELECT kv_key FROM files WHERE request_id=?', id);
  for (const f of files) await env.FILES.delete(f.kv_key);
  await q(env.DB, 'UPDATE requests SET purged_at=COALESCE(purged_at, ?) WHERE id=?', now(), id).run();
}
async function deleteRequest(env, id) {
  const files = await all(env.DB, 'SELECT kv_key FROM files WHERE request_id=?', id);
  for (const f of files) await env.FILES.delete(f.kv_key);
  await env.DB.batch([q(env.DB, 'DELETE FROM files WHERE request_id=?', id), q(env.DB, 'DELETE FROM requests WHERE id=?', id)]);
  return json({ok: true});
}
async function patchFiles(env, req) {
  const body = await readJson(req);
  must(Array.isArray(body.ids) && body.ids.length <= 200 && body.ids.every(x => typeof x === 'string'), 'bad_ids');
  must(body.downloaded_at === null || (typeof body.downloaded_at === 'string' && ISO.test(body.downloaded_at)), 'bad_value');
  if (body.ids.length) await env.DB.batch(body.ids.map(fid => q(env.DB, 'UPDATE files SET downloaded_at=? WHERE id=?', body.downloaded_at, fid)));
  return json({ok: true});
}
async function getFile(env, id) {
  const f = await one(env.DB, 'SELECT * FROM files WHERE id=?', id);
  must(f, 'not_found', 404);
  const obj = await env.FILES.get(f.kv_key, {type: 'arrayBuffer'});
  must(obj, 'purged', 410);
  return new Response(obj, {headers: {'Content-Type': f.mime || 'application/octet-stream', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    'Content-Disposition': `inline; filename*=UTF-8''${encodeURIComponent(f.original_name)}`, ...CORS}});
}

/* ---------- daily cleanup ---------- */
export async function dailyCleanup(env) {
  const days = Number(env.PURGE_DAYS);
  if (!Number.isInteger(days) || days < 1 || days > 365) { console.error('PURGE_DAYS invalid, nothing purged:', env.PURGE_DAYS); return 0; }
  const cutoff = new Date(Date.now() - days * 86400000).toISOString();
  const due = await all(env.DB, `SELECT id FROM requests r WHERE status='approved' AND fully_downloaded_at IS NOT NULL AND fully_downloaded_at<? AND purged_at IS NULL
    AND NOT EXISTS (SELECT 1 FROM files f WHERE f.request_id=r.id AND f.downloaded_at IS NULL)`, cutoff);
  for (const r of due) { try { await purgeRequest(env, r.id); } catch (e) { console.error('purge failed', r.id, e.message); } }
  await q(env.DB, 'DELETE FROM events WHERE at<?', new Date(Date.now() - 86400000).toISOString()).run();
  await q(env.DB, 'DELETE FROM sessions WHERE expires_at<?', now()).run();
  await q(env.DB, 'DELETE FROM login_attempts WHERE at<?', new Date(Date.now() - 86400000).toISOString()).run();
  return due.length;
}

/* ---------- router ---------- */
async function route(req, env) {
  const url = new URL(req.url); const p = url.pathname.replace(/\/+$/, ''); const m = req.method;
  let x;
  if (p === '/api/health') return json({ok: true});
  if (p === '/api/intake' && m === 'POST') return intakeSave(env, req);
  if ((x = p.match(/^\/api\/intake\/([a-f0-9]{64})$/)) && m === 'GET') {
    const r = await byToken(env.DB, x[1], false);
    return json(r.status === 'approved' ? {status: 'approved'} : await publicView(env.DB, r));  // closed link: no personal details
  }
  if ((x = p.match(/^\/api\/intake\/([a-f0-9]{64})\/files$/)) && m === 'POST') return intakeUpload(env, req, x[1]);
  if ((x = p.match(/^\/api\/intake\/([a-f0-9]{64})\/files\/([\w-]+)$/)) && m === 'DELETE') return intakeRemove(env, x[1], x[2]);
  if ((x = p.match(/^\/api\/intake\/([a-f0-9]{64})\/submit$/)) && m === 'POST') return intakeSubmit(env, x[1]);

  if (p === '/api/staff/login' && m === 'POST') return staffLogin(env, req);
  if (p.startsWith('/api/staff/')) {
    const me = await staffAuth(env, req);
    if (p === '/api/staff/session' && m === 'GET') return json({email: me.email});
    if (p === '/api/staff/logout' && m === 'POST') { await q(env.DB, 'DELETE FROM sessions WHERE token_hash=?', me.hash).run(); return json({ok: true}); }
    if (p === '/api/staff/requests' && m === 'GET') return listRequests(env);
    if ((x = p.match(/^\/api\/staff\/requests\/([\w-]+)$/)) && m === 'PATCH') return patchRequest(env, req, x[1]);
    if ((x = p.match(/^\/api\/staff\/requests\/([\w-]+)$/)) && m === 'DELETE') return deleteRequest(env, x[1]);
    if ((x = p.match(/^\/api\/staff\/requests\/([\w-]+)\/purge$/)) && m === 'POST') { await purgeRequest(env, x[1]); return json({ok: true}); }
    if (p === '/api/staff/files' && m === 'PATCH') return patchFiles(env, req);
    if ((x = p.match(/^\/api\/staff\/files\/([\w-]+)$/)) && m === 'GET') return getFile(env, x[1]);
  }
  throw new HttpError(404, 'not_found');
}

export default {
  async fetch(req, env) {
    if (req.method === 'OPTIONS') return new Response(null, {status: 204, headers: CORS});
    try { return await route(req, env); }
    catch (e) {
      if (e instanceof HttpError) return json({error: e.code}, e.status);
      console.error(e); return json({error: 'server_error'}, 500);
    }
  },
  async scheduled(event, env, ctx) { ctx.waitUntil(dailyCleanup(env)); },
};

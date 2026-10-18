// Daily job (GitHub Actions): keeps the free Supabase project awake and deletes
// files from the cloud. Runs with the service role key, which never reaches the browser.
//   1. ping
//   2. approved requests fully downloaded 14+ days ago → delete every stored object, verify, mark purged_at
//   3. files a referrer removed (public.trash) → delete from storage
// Env: SUPABASE_URL, SUPABASE_SERVICE_KEY
const URL_ = (process.env.SUPABASE_URL || '').replace(/\/$/, '');
const KEY = process.env.SUPABASE_SERVICE_KEY || '';
if (!URL_ || !KEY) { console.log('SUPABASE_URL / SUPABASE_SERVICE_KEY not set – skipping'); process.exit(0); }

const PURGE_DAYS = 14, BUCKET = 'intake';
const H = {apikey: KEY, 'Content-Type': 'application/json', ...(KEY.startsWith('eyJ') ? {Authorization: `Bearer ${KEY}`} : {})};

async function call(method, path, body) {
  const res = await fetch(URL_ + path, {method, headers: H, body: body === undefined ? undefined : JSON.stringify(body)});
  const txt = await res.text();
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status} ${txt.slice(0, 300)}`);
  return txt ? JSON.parse(txt) : null;
}
const listAll = async prefix => {
  const out = [];
  for (let offset = 0; ; offset += 100) {
    const page = await call('POST', `/storage/v1/object/list/${BUCKET}`, {prefix, limit: 100, offset});
    out.push(...page.filter(o => o.id).map(o => `${prefix}/${o.name}`));
    if (page.length < 100) return out;
  }
};
const removePaths = async paths => {
  for (let i = 0; i < paths.length; i += 100) await call('DELETE', `/storage/v1/object/${BUCKET}`, {prefixes: paths.slice(i, i + 100)});
};

await call('POST', '/rest/v1/rpc/ping', {});
console.log('ping ok');

const cutoff = new Date(Date.now() - PURGE_DAYS * 86400000).toISOString();
const due = await call('GET', `/rest/v1/requests?select=id,token&status=eq.approved&purged_at=is.null&fully_downloaded_at=lt.${encodeURIComponent(cutoff)}`);
let failed = 0;
for (const r of due) {
  try {
    await removePaths(await listAll(r.token));
    const left = await listAll(r.token);
    if (left.length) throw new Error(`${left.length} objects still there`);
    await call('PATCH', `/rest/v1/requests?id=eq.${r.id}`, {purged_at: new Date().toISOString()});
    console.log('purged request', r.id);
  } catch (e) { failed++; console.error('purge failed', r.id, e.message); }
}

const trash = await call('GET', '/rest/v1/trash?select=storage_path&limit=1000');
if (trash.length) {
  const paths = trash.map(t => t.storage_path);
  await removePaths(paths);
  const list = paths.map(p => `"${p.replace(/"/g, '')}"`).join(',');
  await call('DELETE', `/rest/v1/trash?storage_path=in.(${encodeURIComponent(list)})`);
  console.log('removed', paths.length, 'trashed files');
}
console.log(`done: ${due.length - failed}/${due.length} requests purged`);
if (failed) process.exit(1);

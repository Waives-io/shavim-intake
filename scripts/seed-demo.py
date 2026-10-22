# Resets the DEMO copy (https://shavim-demo.pages.dev) to fresh dummy data: wipes it, then seeds 8 fictional requests.
#   py scripts/seed-demo.py
# Only touches the demo database and file store (ids below), never Holon.
import base64, json, os, random, secrets, subprocess, tempfile, uuid
from datetime import datetime, timedelta, timezone

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KV_ID = '23649df5e42a4019bf29ce50c169e76c'   # shavim-demo-files
DB = 'shavim-demo'
CFG = ['-c', 'branches/demo.wrangler.jsonc']
HERE = tempfile.mkdtemp()
NOW = datetime.now(timezone.utc)
iso = lambda d: (NOW - timedelta(days=d, hours=1)).strftime('%Y-%m-%dT%H:%M:%S.000Z')

def pdf(title):
    """A small but valid one-page PDF."""
    text = f'BT /F1 22 Tf 60 760 Td (Shavim - DEMO document, dummy data) Tj 0 -34 Td /F1 16 Tf ({title}) Tj ET'
    objs = ['<</Type/Catalog/Pages 2 0 R>>', '<</Type/Pages/Kids[3 0 R]/Count 1>>',
            '<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>',
            f'<</Length {len(text)}>>stream\n{text}\nendstream', '<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>']
    out, offs = b'%PDF-1.4\n', []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += f'{i} 0 obj{o}endobj\n'.encode()
    x = len(out)
    out += f'xref\n0 {len(objs)+1}\n0000000000 65535 f \n'.encode() + b''.join(f'{o:010d} 00000 n \n'.encode() for o in offs)
    out += f'trailer<</Size {len(objs)+1}/Root 1 0 R>>\nstartxref\n{x}\n%%EOF'.encode()
    return out

def tz():   # a valid (check digit) but random ID number
    while True:
        d = [random.randint(0, 9) for _ in range(8)]
        for c in range(10):
            s = sum((n * (i % 2 + 1)) - 9 if n * (i % 2 + 1) > 9 else n * (i % 2 + 1) for i, n in enumerate(d + [c]))
            if s % 10 == 0: return ''.join(map(str, d + [c]))

DOCN = {'committee': 'Committee decision', 'psychiatric': 'Psychiatric report', 'social': 'Social report', 'medical': 'Medical summary', 'idcard': 'ID card'}
FN = {'committee': 'החלטת ועדה.pdf', 'psychiatric': 'דוח פסיכיאטרי.pdf', 'social': 'דוח סוציאלי.pdf', 'medical': 'סיכום רפואי.pdf', 'idcard': 'צילום תז.pdf'}
REF = [('אורית גולן', 'orit.demo@example.co.il', '052-3456789'), ('מירב שטרן', 'meirav.demo@example.co.il', '054-7654321'), ('עידו ברק', 'ido.demo@example.co.il', '050-1112233')]

S = [  # name, days ago, status, files {doc: downloaded_days_ago|None}, extra columns, reviews
    ('יוסי כהן', 10, 'in_progress', {'committee': None}, {}, {}),
    ('רונית אברהם', 9, 'in_progress', {'committee': None, 'social': None}, {'last_reminder_at': 2}, {}),
    ('דניאל מזרחי', 2, 'in_progress', {}, {}, {}),
    ('שירה פרץ', 1, 'submitted', {'committee': None, 'psychiatric': None, 'social': None, 'medical': None}, {'submitted_at': 1}, {}),
    ('אבי ביטון', 3, 'submitted', {'committee': None, 'psychiatric': None, 'social': None}, {'submitted_at': 2}, {'committee': 'ok', 'psychiatric': 'replace'}),
    ('מיכל דהן', 4, 'submitted', {'committee': 2, 'psychiatric': 2, 'social': None, 'idcard': None}, {'submitted_at': 3, 'last_download_at': 2}, {}),
    ('עומר פרידמן', 6, 'approved', {'committee': 3, 'psychiatric': 3, 'social': 3}, {'submitted_at': 5, 'approved_at': 4, 'thanks_sent_at': 4, 'last_download_at': 3, 'fully_downloaded_at': 3}, {}),
    ('נועם שפירא', 20, 'approved', {'committee': 5, 'psychiatric': 5, 'social': 5, 'medical': 5}, {'submitted_at': 18, 'approved_at': 6, 'last_download_at': 5, 'fully_downloaded_at': 5, 'archived_at': 1}, {}),
]
q = lambda v: 'NULL' if v is None else "'" + str(v).replace("'", "''") + "'"
sql, kv = ['DELETE FROM doc_reviews; DELETE FROM files; DELETE FROM requests; DELETE FROM events;'], []
for i, (name, ago, status, files, extra, reviews) in enumerate(S):
    rid, token = str(uuid.uuid4()), secrets.token_hex(32)
    rn, re_, rp = REF[i % 3]
    cols = {'id': rid, 'token': token, 'participant_name': name, 'participant_id': tz(), 'ref_name': rn, 'ref_email': re_, 'ref_phone': rp,
            'status': status, 'possible_duplicate': 0, 'created_at': iso(ago), 'updated_at': iso(0)}
    for k, d in extra.items(): cols[k] = iso(d)
    if 'last_download_at' in extra: cols['folder_name'] = f"{name} - {(NOW - timedelta(days=extra['last_download_at'])).strftime('%d.%m.%Y')}"
    sql.append(f"INSERT INTO requests({','.join(cols)}) VALUES ({','.join(q(v) for v in cols.values())});")
    for j, (doc, dl) in enumerate(files.items()):
        fid = str(uuid.uuid4()); key = f'f/{rid}/{fid}'; data = pdf(f'{DOCN[doc]} - sample {i+1}')
        sql.append(f"INSERT INTO files(id,request_id,doc_type,original_name,kv_key,size_bytes,mime,uploaded_at,downloaded_at) VALUES "
                   f"({q(fid)},{q(rid)},{q(doc)},{q(FN[doc])},{q(key)},{len(data)},'application/pdf',{q(iso(ago - min(j, ago)))},{q(iso(dl) if dl is not None else None)});")
        kv.append({'key': key, 'value': base64.b64encode(data).decode(), 'base64': True, 'metadata': {'mime': 'application/pdf', 'name': FN[doc]}})
    for doc, st in reviews.items():
        sql.append(f"INSERT INTO doc_reviews(request_id,doc_type,state,at) VALUES ({q(rid)},{q(doc)},{q(st)},{q(iso(1))});")

npx = 'npx.cmd' if os.name == 'nt' else 'npx'
run = lambda cmd: subprocess.run(cmd, cwd=PROJECT, capture_output=True, text=True, encoding='utf-8', errors='replace')
# wipe the old demo files first
old = run([npx, '-y', 'wrangler@4', 'kv', 'key', 'list', '--namespace-id', KV_ID, '--remote'])
keys = [k['name'] for k in json.loads(old.stdout[old.stdout.index('['):])]
if keys:
    json.dump(keys, open(os.path.join(HERE, 'old.json'), 'w'))
    r = run([npx, '-y', 'wrangler@4', 'kv', 'bulk', 'delete', os.path.join(HERE, 'old.json'), '--namespace-id', KV_ID, '--remote', '--force'])
    print(('OK' if r.returncode == 0 else 'FAILED') + f' wipe {len(keys)} old files')
open(os.path.join(HERE, 'seed.sql'), 'w', encoding='utf-8').write('\n'.join(sql))
json.dump(kv, open(os.path.join(HERE, 'kv.json'), 'w'))
for cmd in ([npx, '-y', 'wrangler@4', 'kv', 'bulk', 'put', os.path.join(HERE, 'kv.json'), '--namespace-id', KV_ID, '--remote'],
            [npx, '-y', 'wrangler@4', 'd1', 'execute', DB, '--remote', '--file', os.path.join(HERE, 'seed.sql'), '-y', *CFG]):
    r = run(cmd)
    print(('OK ' if r.returncode == 0 else 'FAILED ') + ' '.join(cmd[3:6]), (r.stdout + r.stderr)[-300:] if r.returncode else '')

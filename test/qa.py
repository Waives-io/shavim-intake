# Run from the project folder:  python -m http.server 8765   (in one window)
#                               python test/qa.py          (in another)
import asyncio, os, sys, json
from playwright.async_api import async_playwright

BASE = 'http://localhost:8765/'
SHOTS = 'test/shots'
os.makedirs(SHOTS, exist_ok=True)
FIX = 'test/fx'
os.makedirs(FIX, exist_ok=True)
for n in ['vaada.pdf', 'psych.pdf', 'social.pdf', 'tz.jpg']:
    open(f'{FIX}/{n}', 'wb').write(b'%PDF-1.4 test ' + n.encode())
open(f'{FIX}/bad.exe', 'wb').write(b'MZ')

results = []
def check(name, cond, extra=''):
    results.append((bool(cond), name, extra))
    print(('PASS ' if cond else 'FAIL ') + name + (f' — {extra}' if extra else ''))

# Folder picker stub: an OPFS folder standing in for \\JAACOV\...\טפסי קליטת מתמודד חדש
PICKER = """
window.showDirectoryPicker = async () => {
  const root = await navigator.storage.getDirectory();
  const d = await root.getDirectoryHandle('טפסי קליטת מתמודד חדש', {create:true});
  return d;
};
if (window.FileSystemHandle && !FileSystemHandle.prototype.queryPermission) {
  FileSystemHandle.prototype.queryPermission = async () => 'granted';
  FileSystemHandle.prototype.requestPermission = async () => 'granted';
}
"""

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={'width': 1280, 'height': 900}, locale='he-IL')
        await ctx.add_init_script(PICKER)
        page = await ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and 'Failed to load resource' not in m.text and errors.append(m.text))

        # ---------- validation unit checks ----------
        await page.goto(BASE)
        await page.wait_for_selector('#participant_name')
        v = await page.evaluate("""() => ({
          p1: phoneOk('050-1234567'), p2: phoneOk('+972 50 123 4567'), p3: phoneOk('00972501234567'), p4: phoneOk('972-50-1234567'),
          p5: phoneOk('03-1234567'), p6: phoneOk('05012345'), p7: fmtPhone('+972501234567'),
          e1: emailOk('a@b.co.il'), e2: emailOk('a@b'), e3: emailOk(' A@B.COM '), e4: emailFix('dana@gmial.com'),
          t1: tzOk('034567891'), t2: tzOk('34567891'), t3: tzOk('034567892'), t4: tzOk('12'),
          rtl: document.documentElement.dir, lang: document.documentElement.lang
        })""")
        check('phone formats valid (local, +972, 00972, 972)', v['p1'] and v['p2'] and v['p3'] and v['p4'])
        check('phone invalid (landline, short)', not v['p5'] and not v['p6'])
        check('phone normalized to 05X-XXXXXXX', v['p7'] == '050-1234567', v['p7'])
        check('email valid/invalid/trim', v['e1'] and not v['e2'] and v['e3'])
        check('email typo suggestion', v['e4'] == 'dana@gmail.com', v['e4'])
        check('ID checksum valid, padded, invalid', v['t1'] and v['t2'] and not v['t3'] and not v['t4'])
        check('RTL + Hebrew', v['rtl'] == 'rtl' and v['lang'] == 'he')

        # ---------- referrer: inline errors ----------
        await page.screenshot(path=f'{SHOTS}/01-form-desktop.png', full_page=True)
        await page.fill('#participant_id', '123')
        await page.focus('#ref_name')
        err = await page.text_content('#e-participant_id')
        check('ID error on blur', 'לא תקין' in err, err)
        await page.fill('#participant_id', '034567891')
        err = await page.text_content('#e-participant_id')
        check('ID error clears while typing', err.strip() == '', err)
        check('send disabled before required docs', await page.is_disabled('#send'))
        # upload before details → blocked
        await page.set_input_files('#in-committee', f'{FIX}/vaada.pdf')
        await page.wait_for_timeout(300)
        bad = await page.eval_on_selector_all('.field.bad', 'els => els.map(e => e.id)')
        check('upload blocked until details valid', 'f-participant_name' in bad, str(bad))

        await page.fill('#participant_name', 'שגיא רון')
        await page.fill('#ref_name', 'אלה מור')
        await page.fill('#ref_email', 'ella@gmial.com')
        await page.focus('#ref_phone')
        hint = await page.text_content('#e-ref_email')
        check('typo hint shown', 'gmail.com' in hint, hint)
        await page.click('[data-fix]')
        check('typo fix applied', await page.input_value('#ref_email') == 'ella@gmail.com')
        await page.fill('#ref_phone', '+972 52 765 4321')
        await page.focus('#participant_name')
        check('phone formatted on blur', await page.input_value('#ref_phone') == '052-7654321', await page.input_value('#ref_phone'))

        # bad file type
        await page.set_input_files('#in-committee', f'{FIX}/bad.exe')
        await page.wait_for_timeout(200)
        t = await page.text_content('.doc[data-doc=committee] .doc-err')
        check('unsupported file rejected', 'לא נתמך' in t, t)

        # upload 2 required → save later
        await page.set_input_files('#in-committee', f'{FIX}/vaada.pdf')
        await page.wait_for_selector('.doc[data-doc=committee].has')
        check('URL now holds personal token', '?r=' in page.url, page.url)
        token_url = page.url
        await page.set_input_files('#in-psychiatric', f'{FIX}/psych.pdf')
        await page.wait_for_selector('.doc[data-doc=psychiatric].has')
        miss = await page.text_content('#bar .missing')
        check('missing list shows the one left', 'סוציאלי' in miss and 'ועדה' not in miss, miss)
        await page.screenshot(path=f'{SHOTS}/02-form-partial.png', full_page=True)
        await page.click('#later')
        await page.wait_for_selector('.end')
        txt = await page.text_content('.end')
        check('save-later screen with link', 'נשמר' in txt and await page.input_value('.copyrow input') == token_url, txt[:80])

        # come back via link, finish
        await page.goto(token_url)
        await page.wait_for_selector('.doc[data-doc=committee].has')
        check('returning link restores details', await page.input_value('#participant_name') == 'שגיא רון')
        await page.set_input_files('#in-social', f'{FIX}/social.pdf')
        await page.wait_for_selector('.doc[data-doc=social].has')
        check('send enabled when all required in', not await page.is_disabled('#send'))
        # remove + re-add optional
        await page.set_input_files('#in-idcard', [f'{FIX}/tz.jpg'])
        await page.wait_for_selector('.doc[data-doc=idcard].has')
        await page.click('.doc[data-doc=idcard] [data-rm]')
        await page.wait_for_selector('.doc[data-doc=idcard]:not(.has)')
        check('file removal works', True)
        await page.click('#send')
        await page.wait_for_selector('.end')
        check('thank-you screen', 'נשלחו' in await page.text_content('.end h1'))

        # merge: new form, same ID + email → continues existing
        await page.goto(BASE)
        await page.wait_for_selector('#participant_name')
        for k, val in [('participant_name', 'שגיא רון'), ('participant_id', '034567891'), ('ref_name', 'אלה מור'), ('ref_email', 'ella@gmail.com'), ('ref_phone', '0527654321')]:
            await page.fill('#' + k, val)
        await page.set_input_files('#in-medical', f'{FIX}/tz.jpg')
        await page.wait_for_selector('.doc[data-doc=medical].has')
        same = page.url == token_url
        n = await page.eval_on_selector_all('.doc.has', 'e => e.length')
        check('same ID+email merges into existing request', same and n == 4, f'{page.url} has={n}')

        # ---------- phone width form ----------
        m = await b.new_context(viewport={'width': 390, 'height': 844}, locale='he-IL', is_mobile=True, has_touch=True)
        mp = await m.new_page()
        await mp.goto(BASE); await mp.wait_for_selector('#participant_name')
        ow = await mp.evaluate('document.documentElement.scrollWidth')
        check('no horizontal scroll at 390px (form)', ow <= 390, str(ow))
        await mp.screenshot(path=f'{SHOTS}/03-form-phone.png', full_page=True)

        # ---------- Noa ----------
        await page.goto(BASE + '?noa')
        await page.wait_for_selector('#lp')
        await page.screenshot(path=f'{SHOTS}/04-login.png')
        await page.fill('#lp', 'x'); await page.click('#lb')
        await page.wait_for_selector('.lrow[data-id]')
        rows = await page.eval_on_selector_all('.lrow[data-id]', 'e => e.length')
        check('dashboard lists demo + new request', rows == 7, str(rows))
        first = await page.text_content('.lrow[data-id] .pname')
        check('awaiting approval sorted first', first in ('נועם בר', 'יוסי לוי', 'שגיא רון'), first)
        await page.screenshot(path=f'{SHOTS}/05-dashboard.png', full_page=True)
        await page.click('.chip[data-f=late]')
        late = await page.eval_on_selector_all('.lrow[data-id] .pname', 'e => e.map(x => x.textContent)')
        check('7+ days filter shows overdue only', sorted(late) == sorted(['רותם שחר', 'דנה כהן']), str(late))
        await page.click('.chip[data-f=all]')
        await page.fill('#q', '0345')
        names = await page.eval_on_selector_all('.lrow[data-id] .pname', 'e => e.map(x => x.textContent)')
        check('search by ID', set(names) == {'דנה כהן', 'שגיא רון'}, str(names))
        await page.fill('#q', '')
        await page.dispatch_event('#q', 'input')

        # copy link
        await ctx.grant_permissions(['clipboard-read', 'clipboard-write'])
        await page.click('#cplink')
        clip = await page.evaluate('navigator.clipboard.readText()')
        check('copy form link', clip == BASE, clip)

        # reminder for overdue
        await page.click('.lrow[data-id]:has-text("דנה כהן")')
        await page.wait_for_selector('.drawer #remind')
        await page.screenshot(path=f'{SHOTS}/06-drawer-inprogress.png')
        await page.click('#remind')
        msg = await page.input_value('#msg')
        check('reminder lists missing docs + personal link', 'דוח פסיכיאטרי' in msg and '?r=' in msg and 'ועדה' not in msg.split('\n')[2], msg[:120])
        await page.evaluate("window._opened=[]; window.open = (u) => { window._opened.push(String(u)); return null; }")
        await page.click('#viaWa')
        op = await page.evaluate('window._opened')
        check('WhatsApp opens to referrer number with text', bool(op) and str(op[-1]).startswith('https://wa.me/972539876543?text='), str(op)[:90])
        await page.wait_for_timeout(400)
        hist = await page.text_content('.drawer .hist')
        check('reminder date recorded', 'תזכורת אחרונה' in hist, hist)
        await page.click('#back')

        # approve the new request + download
        await page.click('.lrow[data-id]:has-text("שגיא רון")')
        await page.wait_for_selector('.drawer #approve')
        await page.click('#dl')
        await page.wait_for_selector('.modal')
        await page.click('.modal .btn.primary')  # choose folder
        await page.wait_for_selector('.drawer .in')
        await page.wait_for_timeout(500)
        files = await page.evaluate("""async () => {
          const root = await (await navigator.storage.getDirectory()).getDirectoryHandle('טפסי קליטת מתמודד חדש');
          const out = {};
          for await (const [n, h] of root.entries()) { if (h.kind === 'directory') { out[n] = []; for await (const [fn] of h.entries()) out[n].push(fn); } }
          return out; }""")
        folder = [k for k in files if k.startswith('שגיא רון - ')]
        check('folder created with name + date', len(folder) == 1, json.dumps(files, ensure_ascii=False))
        if folder:
            check('4 files written with clear names', len(files[folder[0]]) == 4 and any(f.startswith('טופס החלטת ועדה - שגיא רון') for f in files[folder[0]]), json.dumps(files[folder[0]], ensure_ascii=False))
        check('download button gone after full download', await page.query_selector('#dl') is None)
        await page.click('#approve')
        await page.wait_for_selector('.modal')
        mtxt = await page.text_content('.modal')
        check('approve asks to send thanks', 'תודה רבה, כל מסמכי הקליטה של שגיא רון התקבלו' in mtxt, mtxt[:100])
        await page.click('.modal .btn.primary')
        await page.wait_for_selector('#msg')
        tmsg = await page.input_value('#msg')
        check('thanks text exact', 'תודה רבה, כל מסמכי הקליטה של שגיא רון התקבלו.' in tmsg)
        await page.click('.modal [data-close]')
        await page.click('#back')
        st = await page.text_content('.lrow[data-id]:has-text("שגיא רון") .badge')
        check('status now אושר', st.strip() == 'אושר', st)

        # partial download then add-on: referrer of יוסי לוי adds a file later
        await page.click('.lrow[data-id]:has-text("יוסי לוי")')
        await page.wait_for_selector('#dl')
        await page.click('#dl')
        await page.wait_for_selector('.drawer .in')
        await page.wait_for_timeout(400)
        tok = await page.evaluate("JSON.parse(localStorage.getItem('shavim-demo-v1')).requests.find(r => r.participant_name === 'יוסי לוי').token")
        rp = await ctx.new_page()
        await rp.goto(BASE + '?r=' + tok)
        await rp.wait_for_selector('#in-idcard')
        locked = await rp.eval_on_selector_all('.doc[data-doc=committee] .x', 'e => e.map(x => x.textContent)')
        check('referrer cannot remove a downloaded file', locked == ['התקבל'], str(locked))
        await rp.set_input_files('#in-idcard', f'{FIX}/tz.jpg')
        await rp.wait_for_selector('.doc[data-doc=idcard].has')
        await rp.click('#send'); await rp.wait_for_selector('.end'); await rp.close()
        await page.reload(); await page.wait_for_selector('.drawer #dl')
        await page.click('#dl')
        await page.wait_for_selector('.modal', timeout=1500) if False else None
        await page.wait_for_timeout(800)
        files = await page.evaluate("""async () => {
          const root = await (await navigator.storage.getDirectory()).getDirectoryHandle('טפסי קליטת מתמודד חדש');
          const out = {};
          for await (const [n, h] of root.entries()) { if (h.kind === 'directory') { out[n] = []; for await (const [fn] of h.entries()) out[n].push(fn); } }
          return out; }""")
        yf = [k for k in files if k.startswith('יוסי לוי')]
        check('second download adds into the same folder', len(yf) == 1 and len(files[yf[0]]) == 5, json.dumps(files, ensure_ascii=False))

        # name search: folder exists but request doesn't know it → asks
        await page.evaluate("""async () => { const root = await (await navigator.storage.getDirectory()).getDirectoryHandle('טפסי קליטת מתמודד חדש');
            await root.getDirectoryHandle('נועם בר - 01.10.2026', {create:true}); }""")
        await page.click('#back')
        await page.click('.lrow[data-id]:has-text("נועם בר")')
        await page.click('#dl')
        await page.wait_for_selector('.modal [data-k]')
        opts = await page.eval_on_selector_all('.modal [data-k]', 'e => e.map(x => x.textContent)')
        check('existing folder found by participant name', any('נועם בר - 01.10.2026' in o for o in opts), str(opts))
        await page.click('.modal [data-k="0"]')
        await page.wait_for_timeout(800)
        files = await page.evaluate("""async () => { const root = await (await navigator.storage.getDirectory()).getDirectoryHandle('טפסי קליטת מתמודד חדש');
          const h = await root.getDirectoryHandle('נועם בר - 01.10.2026'); const o=[]; for await (const [fn] of h.entries()) o.push(fn); return o; }""")
        check('files added to the found folder', len(files) == 4, json.dumps(files, ensure_ascii=False))
        await page.click('#back')
        await page.screenshot(path=f'{SHOTS}/07-dashboard-after.png', full_page=True)

        # phone dashboard
        await m.add_init_script(PICKER)
        await mp.goto(BASE + '?noa'); await mp.wait_for_selector('#lp'); await mp.fill('#lp', 'x'); await mp.click('#lb')
        await mp.wait_for_selector('.lrow[data-id]')
        ow = await mp.evaluate('document.documentElement.scrollWidth')
        check('no horizontal scroll at 390px (dashboard)', ow <= 390, str(ow))
        await mp.screenshot(path=f'{SHOTS}/08-dashboard-phone.png', full_page=True)
        await mp.click('.lrow[data-id]')
        await mp.wait_for_selector('.drawer')
        await mp.screenshot(path=f'{SHOTS}/09-drawer-phone.png')

        check('no JS errors', not errors, '; '.join(errors[:5]))
        await b.close()
    bad = [r for r in results if not r[0]]
    print(f'\n{len(results)-len(bad)}/{len(results)} passed')

asyncio.run(main())

# Run from the project folder:  python -m http.server 8765   (in one window)
#                               python test/qa.py          (in another)
import asyncio, os, re, sys, json
from playwright.async_api import async_playwright

BASE = 'http://localhost:8765/'
SHOTS = 'test/shots'
os.makedirs(SHOTS, exist_ok=True)
FIX = 'test/fx'
os.makedirs(FIX, exist_ok=True)
for n in ['vaada.pdf', 'psych.pdf', 'social.pdf', 'tz.jpg']:
    open(f'{FIX}/{n}', 'wb').write(b'%PDF-1.4 test ' + n.encode())
open(f'{FIX}/bad.exe', 'wb').write(b'MZ')

# The QA runs in demo mode: blank apiUrl in the served page so no test data reaches the live Worker
async def demo_mode(ctx):
    async def blank(route):
        r = await route.fetch(); body = await r.text()
        await route.fulfill(response=r, body=re.sub(r"apiUrl: '[^']*',", "apiUrl: '',", body, count=1))
    await ctx.route(re.compile(r'.*localhost:8765/(index\.html)?(\?.*)?$'), blank)

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
        await ctx.add_init_script(PICKER); await demo_mode(ctx)
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
        # upload before details → the file waits, nothing is sent yet
        await page.set_input_files('#in-committee', f'{FIX}/vaada.pdf')
        await page.wait_for_timeout(300)
        note = await page.text_content('.doc[data-doc=committee] .doc-files')
        check('file before details waits ("יועלה אחרי מילוי הפרטים")', 'יועלה אחרי' in note and '?r=' not in page.url, note[:60])
        await page.click('.doc[data-doc=committee] [data-rmp]')
        check('waiting file can be removed', await page.query_selector('.doc[data-doc=committee] [data-rmp]') is None)
        stuck = await page.eval_on_selector('.doc[data-doc=committee] [data-pick]', 'b => b.disabled || b.classList.contains("busy")')
        check('upload button not stuck after blocked upload', not stuck)
        await page.fill('#participant_id', '')
        await page.type('#participant_id', '0345a678912345')
        check('ID field keeps digits only, max 9', await page.input_value('#participant_id') == '034567891', await page.input_value('#participant_id'))

        await page.fill('#participant_name', 'שגיא רון')
        await page.fill('#ref_name', 'אלה מור')
        await page.fill('#ref_email', 'fff@gnai.il')
        await page.focus('#ref_name')
        await page.wait_for_timeout(1500)
        hint = await page.text_content('#e-ref_email')
        check('email with a non-existent domain gets a hint', 'לא מצאנו' in hint, hint)
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
        async with page.expect_file_chooser() as fc:
            await page.click('.doc[data-doc=committee] [data-repl]')
        await (await fc.value).set_files(f'{FIX}/vaada.pdf')
        await page.wait_for_selector('.doc[data-doc=committee] li.old')
        n_cur = await page.eval_on_selector_all('.doc[data-doc=committee] li:not(.old)', 'e => e.length')
        check('"קובץ להחלפה": old file marked replaced, one current file', n_cur == 1, str(n_cur))
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

        # same ID + email on a new form → a NEW request (never hands over the existing one)
        await page.goto(BASE)
        await page.wait_for_selector('#participant_name')
        for k, val in [('participant_name', 'שגיא רון'), ('participant_id', '034567891'), ('ref_name', 'אלה מור'), ('ref_email', 'ella@gmail.com'), ('ref_phone', '0527654321')]:
            await page.fill('#' + k, val)
        await page.set_input_files('#in-medical', f'{FIX}/tz.jpg')
        await page.wait_for_selector('.doc[data-doc=medical].has')
        same = page.url == token_url
        n = await page.eval_on_selector_all('.doc.has', 'e => e.length')
        check('same ID+email opens a new request, not the existing one', not same and '?r=' in page.url and n == 1, f'{page.url} has={n}')

        # ---------- phone width form ----------
        m = await b.new_context(viewport={'width': 390, 'height': 844}, locale='he-IL', is_mobile=True, has_touch=True); await demo_mode(m)
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
        dups = await page.eval_on_selector_all('.lrow[data-id]:has-text("שגיא רון")', 'e => e.length')
        check('dashboard lists demo + 2 new requests, both with the same name and ID', rows == 8 and dups == 2, f'rows={rows} dups={dups}')
        first = await page.text_content('.lrow[data-id] .pname')
        check('awaiting approval sorted first', first in ('נועם בר', 'יוסי לוי', 'שגיא רון'), first)
        await page.screenshot(path=f'{SHOTS}/05-dashboard.png', full_page=True)
        check('no separate 7+ days filter', await page.query_selector('.chip[data-f=late]') is None)
        await page.click('.chip[data-f=in_progress]')
        late = await page.eval_on_selector_all('.lrow[data-id]:has([data-act=remind]) .pname', 'e => e.map(x => x.textContent)')
        check('late requests (in progress) have a reminder button in the row', sorted(late) == sorted(['רותם שחר', 'דנה כהן']), str(late))
        need = await page.eval_on_selector_all('.lrow[data-id]:has-text("דנה כהן") .pill.need', 'e => e.length')
        check('missing required documents are red squares', need == 2, str(need))
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
        await page.wait_for_selector('.modal')
        await page.click('.modal .btn.primary')  # "כן, נשלחה"
        op = await page.evaluate('window._opened')
        check('WhatsApp opens to referrer number with text', bool(op) and str(op[-1]).startswith('https://wa.me/972539876543?text='), str(op)[:90])
        await page.wait_for_timeout(400)
        hist = await page.text_content('.drawer .hist')
        check('update-request date recorded', 'בקשה לעדכון אחרונה' in hist, hist)
        await page.click('#back')

        # per-document review on a submitted request
        await page.click('.lrow[data-id]:has-text("נועם בר")')
        await page.wait_for_selector('.drawer #approve')
        await page.click('.drawer [data-rv=psychiatric][data-st=replace]')
        await page.wait_for_selector('.drawer #remind')
        check('"replace" swaps approve for a reminder', await page.query_selector('.drawer #approve') is None)
        await page.click('#remind')
        msg = await page.input_value('#msg')
        check('reminder lists the document to replace', 'להחליף' in msg and 'דוח פסיכיאטרי' in msg, msg[:160])
        await page.click('.modal [data-close]')
        tok = await page.evaluate("JSON.parse(localStorage.getItem('shavim-demo-v1')).requests.find(r => r.participant_name === 'נועם בר').token")
        rp = await ctx.new_page(); await rp.goto(BASE + '?r=' + tok); await rp.wait_for_selector('.doc[data-doc=psychiatric]')
        check('referrer sees "נדרש להחליף מסמך" (no green ✓)', 'נדרש להחליף מסמך' in await rp.text_content('.doc[data-doc=psychiatric] .doc-state'))
        await rp.set_input_files('#in-psychiatric', f'{FIX}/psych.pdf')
        await rp.wait_for_selector('.doc[data-doc=psychiatric] li.old')
        check('referrer: old file shown as "הוחלף"', 'הוחלף' in await rp.text_content('.doc[data-doc=psychiatric] li.old'))
        await rp.close()
        await page.reload(); await page.wait_for_selector('.drawer .frow.old')
        check('Noa: yellow square "לבדיקה" in the list', await page.locator('.lrow[data-id]:has-text("נועם בר") .pill.chk').count() == 1)
        dtxt = await page.text_content('.drawer .dlist')
        check('Noa: old file struck "הוחלף", new one "חדש — לבדיקה"', 'הוחלף' in dtxt and 'חדש — לבדיקה' in dtxt)
        for d in ['committee', 'psychiatric', 'social']:
            await page.click(f'.drawer [data-rv={d}][data-st=ok]')
            await page.wait_for_timeout(300)
        await page.wait_for_selector('.modal')
        check('all required "תקין" → approved + asks about thanks', 'לשלוח תודה' in await page.text_content('.modal'))
        await page.click('.modal .btn.ghost')
        await page.click('#back')

        # approve the new request + download
        await page.click('.lrow[data-id]:has-text("שגיא רון")')
        await page.wait_for_selector('.drawer #approve')
        await page.click('#dl')
        await page.wait_for_selector('.drawer .in')
        check('download opens no extra dialog', await page.query_selector('.modal') is None)
        await page.wait_for_timeout(500)
        files = await page.evaluate("""async () => {
          const root = await (await navigator.storage.getDirectory()).getDirectoryHandle('טפסי קליטת מתמודד חדש');
          const out = {};
          for await (const [n, h] of root.entries()) { if (h.kind === 'directory') { out[n] = []; for await (const [fn] of h.entries()) out[n].push(fn); } }
          return out; }""")
        folder = [k for k in files if k.startswith('שגיא רון - ')]
        check('folder created with name + date', len(folder) == 1, json.dumps(files, ensure_ascii=False))
        if folder:
            check('3 files written with clear names (the 4th went to the new request)', len(files[folder[0]]) == 3 and any(f.startswith('טופס החלטת ועדה - שגיא רון') for f in files[folder[0]]), json.dumps(files[folder[0]], ensure_ascii=False))
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
        st = await page.eval_on_selector_all('.lrow[data-id]:has-text("שגיא רון") .badge', 'e => e.map(x => x.textContent.trim())')
        check('status now אושר', sorted(st) == ['אושר', 'בתהליך'], str(st))

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

        # existing folder for the participant: reused without asking, same-name file overwritten
        await page.evaluate("""async () => { const root = await (await navigator.storage.getDirectory()).getDirectoryHandle('טפסי קליטת מתמודד חדש');
            const d = await root.getDirectoryHandle('נועם בר - 01.10.2026', {create:true});
            const w = await (await d.getFileHandle('טופס החלטת ועדה - נועם בר.pdf', {create:true})).createWritable(); await w.write('OLD'); await w.close(); }""")
        await page.click('#back')
        await page.click('.lrow[data-id]:has-text("נועם בר")')
        await page.click('#dl')
        await page.wait_for_timeout(1000)
        check('existing participant folder reused without asking', await page.query_selector('.modal') is None)
        files = await page.evaluate("""async () => { const root = await (await navigator.storage.getDirectory()).getDirectoryHandle('טפסי קליטת מתמודד חדש');
          const h = await root.getDirectoryHandle('נועם בר - 01.10.2026'); const o={}; for await (const [fn, fh] of h.entries()) o[fn] = (await (await fh.getFile()).text()).slice(0, 8); return o; }""")
        check('files written into it, same name overwritten', len(files) == 4 and files.get('טופס החלטת ועדה - נועם בר.pdf', 'OLD') != 'OLD', json.dumps(files, ensure_ascii=False))
        await page.click('#back')
        await page.screenshot(path=f'{SHOTS}/07-dashboard-after.png', full_page=True)

        # one file at a time
        await page.click('.lrow[data-id]:has-text("רותם שחר")'); await page.wait_for_selector('.drawer [data-dlf]')
        await page.click('.drawer [data-dlf]'); await page.wait_for_timeout(900)
        files = await page.evaluate("""async () => { const root = await (await navigator.storage.getDirectory()).getDirectoryHandle('טפסי קליטת מתמודד חדש');
          for await (const [n, h] of root.entries()) if (n.startsWith('רותם שחר')) { const o=[]; for await (const [fn] of h.entries()) o.push(fn); return o; } return []; }""")
        check('single-file download saves just that file', len(files) == 1, json.dumps(files, ensure_ascii=False))
        check('…and the rest are still waiting', '(1)' in (await page.text_content('.drawer #dl') or ''))
        await page.click('#back')

        # change password dialog; the eye sits on the right, away from where the password starts
        await page.click('#chpw'); await page.wait_for_selector('.modal #pw0')
        box = await page.eval_on_selector('.modal [data-eye=pw0]', 'b => { const r = b.getBoundingClientRect(), i = b.parentElement.querySelector("input").getBoundingClientRect(); return r.left > i.left + i.width / 2; }')
        check('password eye is on the right side', box)
        await page.fill('#pw0', 'x'); await page.fill('#pw1', 'abcdefgh'); await page.fill('#pw2', 'abcdefgX')
        await page.click('#pwsave')
        check('change password: mismatch caught', 'לא זהות' in await page.text_content('#pwerr'))
        await page.fill('#pw2', 'abcdefgh'); await page.click('#pwsave'); await page.wait_for_timeout(300)
        check('change password: saved and dialog closed', await page.query_selector('.modal') is None)

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

        # file added before the details uploads by itself once they are filled in
        c3 = await b.new_context(locale='he-IL'); await demo_mode(c3); p3 = await c3.new_page()
        await p3.goto(BASE); await p3.wait_for_selector('#participant_name')
        await p3.set_input_files('#in-psychiatric', f'{FIX}/psych.pdf')
        for k, val in [('participant_name', 'מיכה שקד'), ('participant_id', '201234564'), ('ref_name', 'רוני'), ('ref_email', 'roni@gmail.com'), ('ref_phone', '0541112233')]:
            await p3.fill('#' + k, val)
        await p3.focus('#participant_name')
        await p3.wait_for_selector('.doc[data-doc=psychiatric].has', timeout=8000)
        check('waiting file uploads automatically after the details', '?r=' in p3.url)
        await c3.close()

        check('no JS errors', not errors, '; '.join(errors[:5]))
        await b.close()
    bad = [r for r in results if not r[0]]
    print(f'\n{len(results)-len(bad)}/{len(results)} passed')

asyncio.run(main())

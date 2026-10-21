# Live-mode smoke test: the real page talking to a Worker (local or deployed).
#   python -m http.server 8765        (page)
#   npx wrangler dev --local --port 8787   (API; password from .dev.vars)
#   python test/live_smoke.py [API_URL] [PASSWORD]
# The page's apiUrl is swapped in the browser only; index.html is not changed.
import asyncio, os, re, sys
from playwright.async_api import async_playwright

PAGE = 'http://127.0.0.1:8765/'   # same address space as the local Worker (Chrome blocks localhost→127.0.0.1)
API = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8787'
PASS = sys.argv[2] if len(sys.argv) > 2 else re.search(r'^STAFF_PASSWORD=(.*)$', open('.dev.vars', encoding='utf-8').read(), re.M).group(1).strip()
FIX = 'test/fx'; os.makedirs(FIX, exist_ok=True)
for n in ['vaada.pdf', 'psych.pdf', 'social.pdf']:
    open(f'{FIX}/{n}', 'wb').write(b'%PDF-1.4 live smoke ' + n.encode())

results = []
def check(name, cond, extra=''):
    results.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name + (f' — {extra}' if extra else ''))

async def main():
    async with async_playwright() as p:
        # the swapped page counts as 'public' to Chrome; allow it to reach a local Worker (test only)
        b = await p.chromium.launch(args=['--disable-features=LocalNetworkAccessChecks,PrivateNetworkAccessRespectPreflightResults,BlockInsecurePrivateNetworkRequests'])
        ctx = await b.new_context(viewport={'width': 1280, 'height': 900}, locale='he-IL')
        async def swap(route):
            r = await route.fetch(); body = await r.text()
            await route.fulfill(response=r, body=re.sub(r"turnstileSiteKey: '[^']*'", "turnstileSiteKey: '1x00000000000000000000AA'", re.sub(r"apiUrl: '[^']*',", f"apiUrl: '{API}',", body, count=1), count=1))
        await ctx.route(re.compile(r'.*127.0.0.1:8765/(index\.html)?(\?.*)?$'), swap)
        page = await ctx.new_page(); errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.goto(PAGE); await page.wait_for_selector('#participant_name')
        check('live mode (no demo bar)', await page.query_selector('.demo-bar') is None)
        name = 'בדיקה חיה'
        for k, v in [('participant_name', name), ('participant_id', '034567891'), ('ref_name', 'בודקת'), ('ref_email', 'qa@example.co.il'), ('ref_phone', '0521234567')]:
            await page.fill('#' + k, v)
        for doc, f in [('committee', 'vaada.pdf'), ('psychiatric', 'psych.pdf'), ('social', 'social.pdf')]:
            await page.set_input_files(f'#in-{doc}', f'{FIX}/{f}')
            await page.wait_for_selector(f'.doc[data-doc={doc}].has', timeout=15000)
        check('3 files uploaded to the Worker', '?r=' in page.url and len(re.search(r'\?r=([a-f0-9]+)', page.url).group(1)) == 64)
        await page.click('#send'); await page.wait_for_selector('.end', timeout=15000)
        check('submitted', 'נשלחו' in await page.text_content('.end h1'))

        await page.goto(PAGE + '?noa'); await page.wait_for_selector('#lp')
        await page.fill('#lp', PASS); await page.click('#lb')
        await page.wait_for_selector('.lrow[data-id]', timeout=15000)
        row = page.locator('.lrow[data-id]', has_text=name).first
        check('Noa sees the request', await row.count() == 1)
        await row.click(); await page.wait_for_selector('.drawer #approve')
        async with ctx.expect_page() as pop:
            await page.click('.drawer [data-view]')
        v = await pop.value
        # headless Chrome has no PDF viewer, so the PDF arrives as a download of the file's blob
        dl = await v.wait_for_event('download', timeout=15000)
        data = open(await dl.path(), 'rb').read()
        check('Noa opens a file (bytes from the Worker)', dl.url.startswith('blob:') and data.startswith(b'%PDF'), dl.url[:40]); await v.close()
        for d in ['committee', 'psychiatric', 'social']:   # approve document by document
            await page.click(f'.drawer [data-rv={d}][data-st=ok]'); await page.wait_for_timeout(600)
        await page.wait_for_selector('.modal'); await page.click('.modal .btn.ghost')  # no thanks now
        await page.wait_for_selector('.drawer .badge.st-ok', timeout=10000)
        check('approved', True)
        await page.click('#arch'); await page.wait_for_timeout(1200)
        check('archived: gone from main list', await page.locator('.lrow[data-id]', has_text=name).count() == 0)
        await page.click('.chip[data-f=archived]')
        check('archived: under ארכיון', await page.locator('.lrow[data-id]', has_text=name).count() >= 1)
        await page.reload(); await page.wait_for_selector('.lrow, .empty', timeout=15000)
        check('session survives reload (no login screen)', await page.query_selector('#lp') is None)
        check('no JS errors', not errors, '; '.join(errors[:3]))
        await b.close()
    print(f'\n{sum(results)}/{len(results)} passed')

asyncio.run(main())

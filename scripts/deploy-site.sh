#!/usr/bin/env bash
# Deploys the site and the API.
#   bash scripts/deploy-site.sh          Holon (the settings inside index.html + wrangler.jsonc)
#   bash scripts/deploy-site.sh demo     another copy: branches/demo.config.js + branches/demo.wrangler.jsonc
#   Holon site: Cloudflare Pages project "shavim-holon" → https://shavim-holon.waives.io
#         (its own address; the CNAME lives in the waives.io DNS zone on Netlify)
#   API:  Worker "shavim-intake" (D1 + KV); a visit to its old address redirects to the site
set -euo pipefail
cd "$(dirname "$0")/.."
BRANCH="${1:-}"
PROJECT=shavim-holon; WRANGLER=wrangler.jsonc
rm -rf dist && mkdir -p dist
cp index.html manifest.json _headers dist/
cp -r assets dist/
if [ -n "$BRANCH" ]; then
  PROJECT="shavim-$BRANCH"; WRANGLER="branches/$BRANCH.wrangler.jsonc"
  # swap the SHAVIM_CONFIG block for this branch's settings
  py -c "import io,re,sys;p,c=sys.argv[1:3];s=io.open(p,encoding='utf-8').read();n=io.open(c,encoding='utf-8').read().strip();s,k=re.subn(r'window\.SHAVIM_CONFIG = \{.*?\n\};',lambda m:n,s,count=1,flags=re.S);assert k==1;io.open(p,'w',encoding='utf-8',newline='\n').write(s)" dist/index.html "branches/$BRANCH.config.js"
fi
(cd dist && npx -y wrangler@4 pages deploy . --project-name "$PROJECT" --branch main --commit-dirty=true)
npx -y wrangler@4 deploy -c "$WRANGLER"

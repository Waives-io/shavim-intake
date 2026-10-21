#!/usr/bin/env bash
# Deploys the site and the API.
#   Site: Cloudflare Pages project "shavim-holon" → https://shavim-holon.waives.io
#         (its own address; the CNAME lives in the waives.io DNS zone on Netlify)
#   API:  Worker "shavim-intake" (D1 + KV); a visit to its old address redirects to the site
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf dist && mkdir -p dist
cp index.html manifest.json _headers dist/
cp -r assets dist/
(cd dist && npx -y wrangler@4 pages deploy . --project-name shavim-holon --branch main --commit-dirty=true)
npx -y wrangler@4 deploy

#!/usr/bin/env bash
# Deploys the site + API (one Worker): https://shavim-intake.autumn-glitter-1f91.workers.dev
# Only the public files go into dist/; the Worker serves them and answers /api/*.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf dist && mkdir -p dist
cp index.html manifest.json _headers dist/
cp -r assets dist/
npx -y wrangler@4 deploy

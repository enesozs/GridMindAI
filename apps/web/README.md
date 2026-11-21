# GridMind web app

A static Next.js site. It renders JSON written by the Python pipeline into `public/data/` (`uv run gridmind export`) and computes no forecasts or statistics itself.

```bash
npm ci
npm run dev          # http://localhost:3000
npm run build        # static export into out/
npx serve out        # preview the exported site
npx playwright test  # smoke tests against out/ (build first)
node scripts/screenshots.mjs ../../docs/screenshots
```

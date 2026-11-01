# Post-Rebrand Checklist

Follow-ups from PR #6 (rebrand to PaceMind, merged 2026-04-22). Delete this
file once all items are closed.

## 1. Finalize name & domain

- PaceMind + https://pacemind.app are placeholders.
- If a different name/domain is chosen, global find-and-replace
  (~10 meaningful occurrences + OG/meta URLs).
- Key files to touch:
  - `frontend/index.html` (title, OG tags, canonical — lines 8, 11, 13, 16-27)
  - `frontend/src/router/index.js` (meta injection)
  - `frontend/src/utils/seo.js`
  - `frontend/src/locales/{en,it}.json`
  - `frontend/public/{robots.txt,sitemap.xml}`
  - `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`

## 2. Stripe price IDs

Currently empty in `backend/api/billing.py:25-27`:

- `STRIPE_PRICE_MONTHLY`
- `STRIPE_PRICE_YEARLY`   → $79 premium_yearly (create in Stripe dashboard)
- `STRIPE_PRICE_RACE_DAY` → $4 race_day_pass (create in Stripe dashboard)

Also add the three vars to `backend/.env.example` so the expected shape is
documented (currently missing).

## 3. Staging deploy

Only milestone that needs external hosting/domain.

- Frontend: Vercel
- Backend: Railway or Fly.io
- After URL is live:
  - Replace "Demo: coming soon" placeholder in `README.md` (line ~9)
  - Seed a demo account with 2–3 well-known GPX routes for the landing CTA

## 4. Landing assets

- `frontend/public/og-image.png` is referenced in `index.html` (lines 20, 27)
  but the file does not exist — will 404 in production. Need a 1200×630 PNG.
- Produce 1 short product video / animated demo to replace the hero
  placeholder on the landing page.

## Verification

- `cd frontend && npm run build` passes.
- `python -m py_compile` on modified backend files passes.
- Full backend test suite not executed in the PR environment
  (missing `cryptography` bindings). Runs locally with:
  `cd backend && source venv/bin/activate && pytest -m "not slow"`

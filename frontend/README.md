# Frontend — Vue 3 SPA

Vue 3 + Vite single-page app: GPX upload, route analysis, prediction, training plans, race calendar, AI race advisor chat, billing UI.

For the full view/store/component map, see **[../CLAUDE.md](../CLAUDE.md)**.

## Quick Start

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The dev server proxies API calls to the backend at `http://localhost:5000`.

## Tech Stack

- **Vue 3** (`<script setup>`) + **Vite**
- **Pinia** (state) + **Vue Router** (with locale prefix `/:lang?`)
- **Tailwind CSS**
- **Leaflet** (maps) + **ECharts** (elevation/pace charts)
- **Axios** (HTTP, with global interceptor for premium-gating modal)
- **vue-i18n** (en, it)

## Common Commands

```bash
npm run dev          # dev server
npm run build        # production build → dist/
npm run preview      # serve the built bundle
npm run lint         # eslint / prettier (if configured)
```

## Environment

Optional `frontend/.env`:

```
VITE_API_URL=http://localhost:5000/api    # override API base (default points to localhost:5000)
VITE_PLAUSIBLE_DOMAIN=...                  # analytics (dormant if unset)
VITE_POSTHOG_KEY=...                       # analytics (dormant if unset)
```

## Layout

```
frontend/
├── src/
│   ├── views/         # Pages (Home, Analysis, Predict, Training, RaceDashboard, Races, ...)
│   ├── components/    # MapView, AgentChat, PredictionResults, UpgradeModal, ...
│   ├── stores/        # Pinia stores (auth, gpx, prediction, subscription, races, ...)
│   ├── router/        # Routes with `/:lang?` prefix + meta injection
│   ├── services/      # api.js (axios + premium-gating interceptor)
│   ├── locales/       # en.json, it.json (vue-i18n)
│   └── utils/         # seo.js, formatters
├── public/            # Static assets, robots.txt, sitemap.xml
├── index.html         # OG/meta tags
├── vite.config.js
├── tailwind.config.js
└── package.json
```

See **[../CLAUDE.md](../CLAUDE.md)** for the up-to-date list of views, stores, and components.

## Docs

- **[../CLAUDE.md](../CLAUDE.md)** — frontend section: views, stores, components, i18n notes.
- **[../README.md](../README.md)** — product overview, pricing, components.

## Troubleshooting

- **CORS errors:** ensure `CORS_ORIGINS` in `backend/config.py` matches `http://localhost:5173`.
- **API connection failed:** check the backend is running (`curl http://localhost:5000/api/health`).
- **Map not displaying:** verify Leaflet CSS is imported and the GPX has valid coordinates.
- **Strava auth fails:** check `STRAVA_CLIENT_ID/SECRET` in backend `.env` and the redirect URI in the Strava app settings.
- **i18n missing keys:** locale files are `src/locales/{en,it}.json` — pricing values are duplicated in `Pricing.vue`, keep them in sync.

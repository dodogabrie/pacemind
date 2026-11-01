# Contributing to PaceMind

Thanks for your interest in contributing. PaceMind is in active development and we welcome pull requests, bug reports, and feedback from the trail running community.

## Development setup

PaceMind is a monorepo with four components, each with its own dependencies.

### Prerequisites

- Python 3.12+
- Node.js 20+
- SQLite (bundled) — PostgreSQL optional for production parity
- A Strava API application (free at https://www.strava.com/settings/api)
- Optional: Anthropic API key (for the AI advisor), Stripe test keys

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in STRAVA_* and other keys
flask db upgrade
python app.py          # runs on http://localhost:5000
```

### Frontend

```bash
cd frontend
npm install
npm run dev            # runs on http://localhost:5173
```

### Running tests

```bash
cd backend
source venv/bin/activate
pytest                 # all tests
pytest -m "not slow"   # skip model-training tests
```

Frontend build sanity check:

```bash
cd frontend
npm run build
```

## How to contribute

1. **Open an issue first** for anything non-trivial. It saves effort on both sides.
2. **Fork & branch.** Branch names: `feat/...`, `fix/...`, `docs/...`.
3. **Keep PRs focused.** One logical change per PR. Smaller is better.
4. **Write tests** for new behaviour in `backend/tests/` where it makes sense.
5. **Follow the code style.** Backend uses `ruff` (see `.github/workflows/ci.yml`). Frontend uses Prettier defaults.
6. **Update docs.** If you change behaviour, update the relevant section of `README.md` or `CLAUDE.md`.

## What we're looking for

Good first issues (see GitHub Issues with `good first issue` label):

- Frontend i18n additions (we support EN + IT today)
- UX polish on existing views (Prediction, Training, RaceDashboard)
- Extra test coverage for edge cases in the prediction pipeline
- Documentation and tutorials
- Bug fixes

Bigger contributions welcome — discuss in an issue first:

- New enrichment sources (e.g. air-quality, trail-condition APIs)
- Additional languages
- Strava alternatives (Garmin Connect, Coros)
- Mobile (PWA) improvements

## What we won't merge

- Changes that break the free-tier user experience.
- Dependencies with incompatible licenses.
- Features that require cross-user data mixing (we keep every athlete's model isolated).
- Bypasses of the billing / premium gating.

## Security

If you find a security issue, please **do not open a public issue**. Email the maintainer directly (see the About page of the app) so we can coordinate a fix.

## Code of conduct

Be kind. Assume good faith. Focus on the work, not the person. We reserve the right to remove comments or contributions that are disrespectful or that violate community standards.

## License

By contributing, you agree that your contributions will be licensed under the repository's [Mozilla Public License 2.0](LICENSE).

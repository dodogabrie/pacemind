# Changelog

All notable changes to PaceMind will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Rebrand to PaceMind.** New name, tagline ("AI pacing coach for trail & ultra racing"), favicon and landing copy.
- **Public pricing page** at `/pricing` with Free / Premium / Race Day Pass comparison, FAQ and Coach & Team waitlist.
- **SEO foundation**: OpenGraph, Twitter card, JSON-LD `SoftwareApplication`, canonical URLs, per-route meta titles/descriptions, `robots.txt` and `sitemap.xml`.
- **Hard paywall** on premium backend endpoints: race report generation (`/api/training-plan/<id>/complete` and `/race-report`), plan compliance (`/api/training-plan/<id>/compliance`), weather forecast (`/api/weather/forecast`). Returns 403 with a `feature` field so the frontend can show the contextual upgrade modal.
- **Contextual upgrade modal**: axios interceptor catches premium-gated 403s and opens `UpgradeModal` with feature-specific headline and trust row (cancel anytime, 7-day money-back, link to pricing).
- **Analytics scaffold**: Plausible and PostHog integration via env vars (`VITE_PLAUSIBLE_DOMAIN`, `VITE_POSTHOG_KEY`). Dormant when unset.
- **Waitlist endpoint** `/api/billing/waitlist` for the upcoming Coach & Team plan.
- **Home pricing preview** section with link to the full pricing page.
- **Dev-mode bypass** in `requires_premium` decorator (consistent with existing dashboard logic).
- Community scaffolding: `CONTRIBUTING.md`, `CHANGELOG.md`, GitHub issue and PR templates.

### Changed
- Home hero copy rewritten to be outcome-driven ("Finish on target time") instead of technology-forward ("Physics-based performance modeling").
- `requires_premium` decorator now accepts an optional feature name (`@requires_premium('race_report')`) while remaining backwards-compatible with `@requires_premium`.
- README repositioned for market readers: Why / Who / Pricing / What's under the hood.

### Notes
- Replace `https://pacemind.app` and `PaceMind` placeholders throughout the codebase when you finalise the domain and brand.

---

_Historical releases (pre-rebrand) were untagged. Future versions will be tagged starting with v0.1.0._

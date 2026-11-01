# Phase 3 — Direct device integrations

**Status:** 📋 planned — **the Garmin application should be submitted on day 1**
**Estimate:** days of engineering, weeks of waiting
**Depends on:** [Phase 1](02-activity-abstraction.md) for the code; **nothing**
for the paperwork
**Cost:** €0 in fees (no published per-request pricing), paid in calendar time

---

## Why this rather than an aggregator

See [05 — Aggregators decision record](05-aggregators-decision.md) for the full
argument. Short version: Garmin is the majority of our target market and we can
integrate it directly for free; an aggregator's floor is $399/mo with no free
tier. The aggregator's real value is the long tail, which is worth much less to
us once Garmin is handled.

## Priority order

| Provider | Access | Friction | Why this rank |
|---|---|---|---|
| **Garmin** — Activity API (Connect Developer Program) | partner approval, application form, use case + privacy policy review | **high, and slow** — reported anywhere from days to weeks; sign-ups have been paused at times | Largest share of trail runners. Apply first *because* it is slow. |
| **Polar** — AccessLink API | self-service registration | **low** | Use it as the test bed: it exercises the whole OAuth + webhook path for free while Garmin sits in a queue. |
| **COROS** — Open API | partner request | medium | Growing fast among trail runners. |
| **Suunto** | OAuth + webhook | medium | Strong in European trail. |
| Wahoo / Fitbit / Decathlon | OAuth | low-medium | Long tail; only if demand shows up. |

Verify each program's current status and terms before planning around it —
Garmin does not publish commercial terms, and program availability has changed.

## Shared architecture

Phase 1 already put the seams in place. Each provider is:

1. A row value in `user_connections.provider` (phase 0).
2. An OAuth handler pair — `/api/connections/<provider>/authorize` and
   `/callback` — generalising `backend/api/auth.py:54,61`.
3. A normalizer in `backend/services/activity_ingest/normalizers/`.
4. A registry entry.

Nothing else changes. If adding a provider touches a service outside that list,
the abstraction from phase 1 is leaking and should be fixed rather than worked
around.

### Webhooks

Garmin and Polar both **push**. That is strictly better than Strava's polling
sync and simplifies things:

```
POST /api/webhooks/<provider>
  → verify signature / ping token
  → 200 immediately (providers retry aggressively and penalise slow endpoints)
  → enqueue: fetch the activity/FIT, normalize, ActivityIngestService.ingest()
```

Requirements that are easy to get wrong:

- **Respond fast and always 200** for well-formed pushes; do the work
  asynchronously. A slow endpoint gets throttled or disabled.
- **Verify authenticity** — signature or shared secret per provider. This is a
  public unauthenticated endpoint.
- **Idempotency** — providers redeliver. `dedup_key` (phase 1) covers this, but
  the handler must also tolerate concurrent redelivery of the same activity.
- **Backfill on connect** — pull historical activities once at connection time;
  webhooks only cover what happens after. Garmin's backfill is itself
  asynchronous (request → pushed later), so the connect flow must not block on it.
- **Deregistration** — handle the provider's "user revoked access" push by
  marking `user_connections.status = 'revoked'` and stopping, rather than
  retrying forever.

### Rate limits and quotas

Each provider has its own. Centralise the throttling rather than reimplementing
it per normalizer — there is an existing rate limiter in the root tests
(`tests/`) and Flask-Limiter in the app; pick one place and stick to it.

## Sequencing

```
day 1        submit Garmin application (free, do it before writing any code)
week 1-3     phases 0-2 ship — the product works without any device API
week 2       Polar AccessLink: full OAuth + webhook + backfill, end to end
             → proves the architecture on a real provider
Garmin approval arrives (whenever): the normalizer is ~a day's work because
             the FIT parser already exists from phase 2
then         COROS / Suunto on demand
```

The point of this ordering: by the time Garmin says yes, the only new code is a
normalizer and an OAuth handler. If Garmin says no, phases 0-2 still deliver a
product that works with every watch on the market via bulk import.

## Open questions to resolve before applying

- [ ] Do Garmin's terms permit using activity data to calibrate a per-user
      prediction model? (This is the same question we should answer for Strava.)
- [ ] Do we need a published privacy policy and DPA before applying? Almost
      certainly yes — `frontend/src/views/Privacy.vue` exists; check it covers
      device data.
- [ ] Is there a setup fee? Third-party sources mention one; it is not on
      Garmin's official pages. Ask directly before budgeting.

## Acceptance criteria (per provider)

- [ ] Connect from the settings panel, see the connection listed.
- [ ] Historical backfill completes with visible progress.
- [ ] A new activity recorded on the watch appears in PaceMind without user
      action, within minutes.
- [ ] Disconnect revokes cleanly; previously imported activities are retained.
- [ ] An activity already imported from Strava is not duplicated.

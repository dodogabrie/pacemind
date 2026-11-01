# Decision record — Wearable data aggregators

**Status:** ✅ decided — **defer**. Revisit on the triggers listed below.
**Date:** 2026-08-21
**Decision:** Do not adopt an aggregator now. Build phases 0-2, apply to Garmin
directly, and keep the architecture such that adopting one later is a single
normalizer.

---

## Options considered

Aggregators expose 300-500+ wearables and health apps behind one API and one
OAuth flow, removing the per-provider approval work.

| Provider | Floor price | What it includes | Free tier |
|---|---|---|---|
| **Terra** | $399/mo annual, $499/mo monthly | 100k credits/mo ≈ ~500 active users at ~200 credits/user/mo; overage $0.005/credit, $0.003 above 1M | **No.** 30-day money-back guarantee. Has a startup-credits programme and can pause an account up to 3 months during development. |
| **ROOK** | $399/mo (Core, ≤750 active users) → $999 (Core+, ≤5k) → $1,999 (Business, ≤15k) → custom | sandbox on all plans | **No.** Note: notification webhooks and data ingestion are **add-ons at $99-499/mo** — i.e. the parts we actually need. |
| **Spike** | priced on MAU, not published | 500+ integrations | — |
| **Garmin direct** | no published per-request fee (not confirmed free either) | Activity API + push webhooks with the FIT file | partner approval, days to weeks |

Prices read from vendor pages in August 2026; they change and are negotiable.
Confirm with sales before budgeting.

## The argument

### 1. The floor is wrong for our stage

Premium is **$9/mo** monthly, **$6.58/mo** billed yearly
(`frontend/src/views/Pricing.vue:65`).

$399/mo ÷ $9 = **~45 paying subscribers just to break even on the aggregator**,
~61 if they are all on the yearly plan — before servers, Anthropic tokens, or
Stripe fees.

### 2. Freemium makes it worse: aggregators bill on *connected* users

They charge per active/connected user, not per paying user. With our free tier,
700 free users connecting a Garmin means paying for 700 while monetising 40.
That is cost scaling with the unmonetised part of the funnel — the worst
possible shape at our stage.

**The mitigation is real and clean:** make device auto-sync a Premium feature.
Then ROOK Core is $399 ÷ 750 ≈ **$0.53/user/mo against $9 of revenue** — a fine
margin. So the aggregator is not expensive *per se*; it is expensive *before
product-market fit*. That reframing is the whole decision.

### 3. An aggregator does not solve Garmin for us

Garmin is plausibly 60-70% of our target market, and we can integrate it
**directly, with no recurring fee** — paid only in approval time. An
aggregator's genuine value is the long tail: Suunto, COROS, Polar, Wahoo,
Fitbit, Apple Health.

> If we get Garmin direct, an aggregator loses roughly half its value to us.
> Finding out costs only the time to fill in an application.

### 4. Bulk import covers everyone today, for free

[Phase 2](03-file-ingest.md) supports **every watch on the market** via vendor
export archives, at zero marginal cost, with one manual step per user. That is
worse UX than auto-sync, but it removes the *blocking* problem — nobody is
turned away for owning the wrong device — which is what the $399/mo would
actually be buying right now.

## What makes this reversible

[Phase 1](02-activity-abstraction.md) defines `ActivityIngestService` with
per-source normalizers behind one interface. An aggregator is **just another
normalizer** plus a registry entry. Adopting Terra or ROOK in six months is a
new file, not a migration.

That is why this is not a fork in the road: it is a decision we can defer at
near-zero cost while we have more information and more revenue.

## Revisit triggers

Adopt an aggregator when **any** of these becomes true:

- [ ] Garmin rejects our application, or the queue exceeds ~2-3 months.
- [ ] We pass ~50-60 Premium subscribers (the break-even point above).
- [ ] "My COROS/Suunto isn't supported" becomes a leading churn or
      support-volume reason.
- [ ] We need a provider whose direct API is closed to companies our size.

## When we do revisit

- Email **Terra about the startup-credits programme** before looking at the list
  price; they also pause accounts during development.
- Ask **ROOK for a price inclusive of the webhooks add-on** — the Core headline
  price excludes exactly what we need, so a naive comparison is wrong.
- Ask **Garmin directly** about commercial terms and any setup fee; nothing is
  published.
- Re-run the per-user maths against whatever Premium costs at that point, and
  against actual connected-vs-paying ratios rather than guesses.

## Sources

- [ROOK pricing](https://www.tryrook.io/pricing)
- [Terra pricing](https://tryterra.co/pricing)
- [Terra — sandbox / trial discussion](https://tryterra.co/community/request-for-free-developer-sandbox-access)
- [Garmin API pricing — what does it actually cost?](https://aifitnessapi.com/pricing/garmin-api-pricing)
- [The real cost of wearables integration: build vs buy](https://www.themomentum.ai/blog/the-real-cost-of-wearables-integration-in-2025-build-vs-buy-analysis)
- [Spike — Garmin API integration](https://www.spikeapi.com/blog/garmin-api-integration-spike)
- [ROOK — Garmin integration](https://www.tryrook.io/wearable-api-sdk/integrations/garmin)

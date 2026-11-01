# Code Quality Audit Tracker

This file tracks an iterative code-quality audit of the `trail_gpx_analyzer` (PaceMind) codebase. Each session focuses on a bounded slice of the system, fixes concrete issues, and hands off context to the next iteration.

> **For the next iteration:** Read the **Status** section first, then **How to continue**, then the deferred items in **Backlog**. Each session should pick one focus area, drive it to a clean state, and update this file.

---

## Status

- **Current branch:** `claude/quality-control-markdown-MlIv0`
- **Last session date:** 2026-04-28
- **Last focus area:** Training plan API (`backend/api/training_plan.py`)
- **Result:** 8 issues fixed (real correctness bugs: PATCH `update_workout_day` accepting stringy numerics that crash week-totals sum() with TypeError, and CRLF/quote injection in `export_ics` Content-Disposition; six 500-instead-of-400 input-validation gaps in `update_pace_zones` / `update_preferences` / `update_plan`; one swallowed `TrainingLoadService` exception with no log line). Backend test suite: **235 tests pass** (219 baseline + 16 new in `tests/test_api/test_training_plan_audit.py`). Ruff clean on the touched files.

---

## How to continue

1. Pick **one** focus area from the **Backlog** (or scan a new one). Keep blast radius small — one subsystem per session.
2. Read this file end-to-end so you don't redo prior work or repeat the same patterns.
3. Use the same heuristics that drove the prior pass (see **Heuristics used**).
4. Fix concrete bugs, not stylistic nits. Prefer minimal diffs.
5. Append a new **Session log** entry with: focus, files touched, issue list, verification.
6. Update **Backlog** — mark items done, remove duplicates, add new findings.
7. Commit on the current audit branch (see **Status**) with message `chore(audit): <focus-area> — <n> fixes`.

---

## Heuristics used (kept consistent across sessions)

These cheap greps surface high-signal issues fast:

```bash
# Bare except / silent failures
grep -rn "except:" backend/ --include="*.py"
grep -rn "except Exception" backend/ --include="*.py"  # Then audit each for legitimacy

# Mutable default args
grep -rn "def .*=\[\]\|def .*={}\|def .*=set()" backend/ --include="*.py"

# HTTP without timeouts
grep -rn "requests\.\(get\|post\|put\|delete\)" backend/ --include="*.py"
grep -rn "timeout=" backend/ --include="*.py"  # cross-reference

# Deprecated datetime
grep -rn "datetime\.utcnow\|datetime\.now()" backend/ --include="*.py"

# File ops without encoding
grep -rn "open(" backend/ --include="*.py" | grep -v "encoding="

# Comparisons with None / True / False
grep -rn "== None\|!= None\|== True\|== False" backend/ --include="*.py"

# Hard-coded paths and secrets
grep -rn "'/Users/\|'/home/" backend/ --include="*.py"
grep -rn "sk-\|AKIA" backend/ --include="*.py"
```

Plus: scan files >500 lines for cohesion problems, look for `db.session.commit()` directly in services (should go through repos), and audit threading code for context leaks.

---

## Session log

### Session 7 — 2026-04-28 — Training plan API

**Focus:** `backend/api/training_plan.py` (520 lines) — largest API blueprint, flagged in the medium-impact backlog as needing input-validation review. Owns plan CRUD, workout-day PATCH, pace-zone overrides, preferences, ICS export, and the aggregated dashboard endpoint.

**Files touched:**
- `backend/api/training_plan.py`
- `backend/tests/test_api/test_training_plan_audit.py` (new)

**Issues fixed:**

1. **`update_workout_day` — stringy numerics crash week-totals (line 140 pre-fix).** `EDITABLE_DAY_FIELDS` lets the caller PATCH `distance_km`, `duration_min`, `elevation_m`, `intensity`. Values were applied as-is into the day dict via `day[field] = data[field]`, then the per-week recompute below ran `sum(d.get('distance_km', 0) or 0 for d in week.get('days', []))`. A caller that PATCHed `{"distance_km": "10"}` (JSON string — easy to send by accident from a stringly-typed frontend or curl) would *successfully* mutate the JSON column to a string, then crash the totals sum() with `TypeError: unsupported operand type(s) for +: 'int' and 'str'` — returning a 500 *and* leaving the plan in a corrupted state where every subsequent dashboard load also crashes the same sum(). Added a module-level `DAY_FIELD_NUMERIC_BOUNDS` table (`{field: (caster, lo, hi)}`) and a try/except coercion+range check before the field write. Bad input now returns 400 with a clear message, and the value gets normalized to float before being stored. **Real correctness bug** — easy to hit, leaves persistent corruption.
2. **`export_ics` — CRLF/quote injection in `Content-Disposition` (line 263 pre-fix).** Header was built as `f'attachment; filename="{plan.plan_name.replace(" ", "_")}.ics"'`. `plan_name` is user-controlled (PUT `update_plan` writes it directly to a `db.String(255)` column). A name containing `\r\nX-Foo: bar` smuggles arbitrary headers into the response; a name containing `"` breaks the quoted filename param so downstream proxies misparse the header. Added a `re.sub(r'[\r\n"\\/]+', '_', ...)` pass plus a non-empty fallback to `'training_plan.ics'`. **Real header-injection vector.**
3. **`update_pace_zones` — `float()` and dict-iteration crash with 500 instead of 400 (lines 380-382 pre-fix).** `data['zones'].items()` raised `AttributeError` if `zones` wasn't a dict; `float(zone_data['min_pace'])` raised `ValueError` on a non-numeric pace; `'min_pace' in zone_data` raised `TypeError` if `zone_data` wasn't a dict. All three surfaced as 500s. Added an `isinstance(data['zones'], dict)` precheck, a per-zone `isinstance(zone_data, dict)` precheck, a try/except around the `float()` calls, and a `min_pace < max_pace` sanity check (was missing entirely — a user could save inverted bands).
4. **`update_preferences` — `int()`/`float()` for `strength_training_days`/`max_hours_per_day` crash with 500 (lines 477, 481 pre-fix).** The `PREF_VALIDATORS` block below already wraps its conversions in try/except, but these two fields were validated *before* that block with raw casts. A caller passing `{"strength_training_days": "two"}` got a 500. Wrapped both in `try/except (TypeError, ValueError)` to return 400 with a typed error message.
5. **`update_plan` — no validation on `weeks` and `plan_name` (lines 68-76 pre-fix).** `plan.weeks = data['weeks']` blindly accepted whatever JSON was there — a caller passing `{"weeks": null}` or `{"weeks": "oops"}` overwrote the plan column, and every subsequent compliance/dashboard call then crashed when iterating `plan.weeks`. Added `isinstance(data['weeks'], list)` check. Added a non-empty-string check for `plan_name` (DB column is `nullable=False` but doesn't enforce non-empty), and pre-trim/cap to the column's 255-char limit so the DB doesn't have to.
6. **`get_dashboard` — silent `except Exception: training_load = None` (line 216 pre-fix).** `TrainingLoadService` errors were swallowed with no log line, so a real bug in the load computation would never surface. Added `logger.warning("get_training_load failed for user_id=%s", user.id, exc_info=True)`. Also dropped the redundant trailing `else: training_load = None` (already initialised to `None` two lines above).
7. **`get_dashboard` — race_countdown one-liner conditional (line 224 pre-fix).** A confusing `delta = X if isinstance(...) else Y` ternary that mixed `.date()` calls with raw subtraction. Per the model `race_date` is `db.Column(db.DateTime)` so the non-datetime branch was dead under current usage. Split into a two-line block with a comment and the `isinstance` guard kept defensively for future migrations.
8. **`update_workout_day` — duplicate `compute_step_summaries` import (line 107 pre-fix).** `from services.workout_service import validate_steps, compute_step_summaries` was imported up top in the validation block but only `validate_steps` is used there; `compute_step_summaries` is imported again 24 lines later in the actual usage block. Removed from the upper import.

Also: added a module-level `logger = logging.getLogger(__name__)` (the file had no logger at all) and a top-level `import re` for the filename sanitization.

**Verification:**
- `py_compile` clean.
- `ruff check api/training_plan.py tests/test_api/test_training_plan_audit.py` — clean.
- 16 new tests in `tests/test_api/test_training_plan_audit.py` covering: stringy/negative/out-of-range numeric PATCH (3); valid numeric PATCH still recomputes week totals (1); `update_plan` rejects non-list weeks / empty / non-string plan_name (3); `update_pace_zones` rejects non-dict zones / non-numeric pace / inverted min≥max (3); `update_preferences` typed errors for both fields (2); `export_ics` strips CRLF + balances quotes + falls back on whitespace-only name (3); `get_dashboard` race_countdown future + clamped-to-zero past (2). All 16 pass.
- Full backend test suite: **235 tests pass** (`pytest tests --ignore=tests/test_api/test_race_brief_pdf.py`; same `fpdf` ignore as prior sessions). Was 219 prior to this session (213 from Session 5 + 6 from Session 6) → 219 + 16 = 235. No regressions.

**Not changed (intentionally deferred):**
- **`weeks` schema validation.** This pass only checks `isinstance(weeks, list)` — a caller can still PUT a list of nonsense dicts. A proper JSON-schema validation pass would benefit the whole training-plan write path (PATCH workout day, PUT plan, generate plan), but it's a cross-cutting concern that deserves its own session. File a backlog item.
- **`infer_terrain_profile` `int()` parse (line 515).** Already wrapped in try/except, so this is a 200 with default-90 fallback, but the silent `except ValueError: lookback = 90` could log a debug line. Cosmetic.
- **Inline imports inside route handlers.** A dozen `from services.X import Y` statements live inside the route bodies (`PlanComplianceService`, `TrainingLoadService`, `RaceReportService`, etc.). This is a deliberate circular-import-avoidance pattern in the codebase; not worth changing in an audit pass.
- **`@requires_premium` dev-mode bypass via `os.environ.get('FLASK_ENV')`.** Same pattern as `api/billing.py` (flagged in Session 4). Standardizing on `current_app.debug` would be project-wide; out of scope.
- **`prediction_repo.get_latest_for_gpx` called with no try/except in `get_dashboard` (line 230).** A DB error there would 500 the whole dashboard. Lower-priority than `training_load`'s suppression because the prediction lookup is a single query and unlikely to fail mid-request, but worth a defensive try/except in a future pass.

---

### Session 6 — 2026-04-28 — Plan engine

**Focus:** `backend/services/plan_engine.py` (1490 lines) — largest service in the backend, owns the four-layer training plan generator (phase assignment → weekly targets → daily distribution → race-profile customization). Flagged in the High-impact backlog and never code-quality reviewed since it landed.

**Files touched:**
- `backend/services/plan_engine.py`
- `backend/tests/test_services/test_plan_engine_audit.py` (new)

**Issues fixed:**

1. **`apply_key_sections` — descent annotation leaks across weeks (line 1084 pre-fix).** The function has `descents = [s for s in key_sections if s.get('type') == 'steep_descent']` in the outer scope, then inside the per-week / per-day loop it does `if wt == 'easy' and descents and not day['notes']: ...; descents = []  # only annotate one easy day per week`. The trailing assignment **rebinds the outer `descents`** to an empty list, so once *any* easy day in *any* week is annotated, every subsequent week's check `if descents` is falsy and skipped. The inline comment explicitly says the intent is "one annotation per week" — but the code annotates one easy day across the **entire plan**. Replaced with a per-week `descent_annotated` flag and a `has_descents = any(...)` precheck so the outer-scope state can't leak. **Real correctness bug** for any plan with steep_descent key sections — only ~1/N weeks gets the descent practice note instead of all N.
2. **`apply_key_sections` — `week.get('theme') == 'Base'` is always false (line 1066 pre-fix).** The check fed `reps = 6 if week.get('theme', '') == 'Base' else 8` for Base-week hill_repeats. But themes are constructed by `_phase_theme()` which returns full strings like `"Base — aerobic foundation"`, never the bare token `"Base"`. The comparison was always false, so Base weeks silently got 8-rep hill repeats instead of the intended 6 — i.e. the early-base athlete was prescribed Build-week intensity at the neuromuscular-priming stage. Switched to `is_base_week = week.get('theme', '').startswith('Base')` precomputed once per week. **Real correctness bug** — Cat 1 athletes in particular are supposed to ease into hill work and were getting heavier dosing than the coaching plan calls for.
3. **`compute_weekly_targets` — magic numbers `1.6`, `2.0`, `1.7` ignored named constants (lines 461, 466, 469 pre-fix).** `WEEKLY_MIN_LR_MULTIPLIER = 1.6` and `PEAK_MIN_LR_MULTIPLIER = 1.7` were declared at lines 152-153 explicitly to be the source of truth, but the Base/Build/Peak floor checks hardcoded the literals. `PEAK_MIN_LR_MULTIPLIER` was *defined-but-never-used* (verified by grep across the whole backend). The Build branch used `2.0` with no named constant. Drift hazard: any future tune of the constant silently disagrees with the actual computation. Added `BUILD_MIN_LR_MULTIPLIER = 2.0` and replaced all three call sites with the constants. No semantic change, but the constants are now actually load-bearing.
4. **`compute_weekly_targets` — phase-index lists recomputed on every loop iteration (O(n²)).** The loop body had three `[i for i, p in enumerate(phases) if p == 'X']` list comprehensions (`base_indices`, `build_indices`, `taper_indices`) plus an `if week_idx in progression_weeks` membership check, all rebuilt fresh each iteration. With `total_weeks` n the function scaled O(n²); n is small (4-30) so this isn't catastrophic, but it's pure waste and obscures intent. Lifted all four lookups out of the loop and switched to O(1) dict lookups (`progression_pos`, `base_pos_by_idx`, `build_pos_by_idx`, `taper_pos_by_idx`). Also caches `n_taper` once.
5. **`validate_plan_feasibility` — dead `< float('inf')` guard (line 1454 pre-fix).** The mountain-budget warning checked `mountain_budget is not None and mountain_budget < float('inf') and ...`. Tracing `_mountain_budget_per_week`: it returns `None` or a finite `float(...)` from `mountain_access_per_week` / `mountain_access_per_month / 4.33` / `len(mountain_days)` — there's no codepath that could yield `inf`. Removed the dead clause and added a one-line code comment so it doesn't get speculatively re-added.

**Verification:**
- `py_compile` clean on both `services/plan_engine.py` and `tests/test_services/test_plan_engine_audit.py`.
- 6 new smoke tests in `tests/test_services/test_plan_engine_audit.py`:
  - `test_apply_key_sections_descent_annotation_per_week_not_per_plan` — across 3 weeks each annotates exactly 1 easy day (was: only the first week did).
  - `test_apply_key_sections_base_hill_repeats_uses_6_reps` — Base week's hill_repeats title contains `6x`, Build's contains `8x` (was: both got `8x`).
  - `test_apply_key_sections_no_descents_leaves_notes_alone` — sanity: no steep_descent section → no notes added.
  - `test_lr_multiplier_constants_used_in_compute_weekly_targets` — uses single-phase calls (`phases=['Base']`, `['Build']`, `['Peak']`) so the 10%-week-over-week cap can't bind, then asserts each phase's `weekly_km / long_run_km` matches its constant. Build correctly hits 2.000, Peak hits 1.698 (≈ 1.7 within rounding).
  - `test_compute_weekly_targets_smoke_realistic_plan` — 7-week cat_2 plan still respects the global `WEEKLY_MIN_LR_MULTIPLIER` floor on every progression week.
  - `test_validate_plan_feasibility_mountain_budget_warning_still_fires` — mountain_budget=1, two mountain workouts in the week → `mountain_budget_exceeded` warning still emitted (regression on the dead-guard cleanup).
- Sandbox lacks numpy/pandas/sklearn (`conftest.py` imports them at module scope), so `pytest` cannot collect tests through the standard harness. Worked around it by exec'ing each test function directly via `importlib.import_module + getattr(mod, 'test_*')`. Across all 4 existing plan_engine test modules (`test_plan_engine_caps`, `test_plan_engine_terrain`, `test_plan_engine_mountain_budget`, `test_validate_plan_feasibility`) plus the new audit module: **28 / 28 pass** (22 existing + 6 new). No regressions.

**Not changed (intentionally deferred):**
- **Subtle Peak-floor drift after the 10% cap.** Lines 485-494 cap `weekly_km` at `prev_non_recovery.weekly_km * 1.10`, then lines 537-543 only re-enforce the *global* `WEEKLY_MIN_LR_MULTIPLIER = 1.6` floor — never `BUILD_MIN_LR_MULTIPLIER` or `PEAK_MIN_LR_MULTIPLIER`. So a Peak week whose pre-cap target was 1.7×LR but got reduced by the 10% cap will settle at the 1.6× floor instead of 1.7×. The audit pass kept the constants as documented coaching intent but didn't change the post-cap restoration logic — that's a coaching-rules decision, not a code-quality fix.
- **Race-week volume capped below race distance.** Line 481 sets `weekly_km = RACE_WEEK_EXTRA_KM + race_distance_km` for the Race phase, then line 533 caps to `max_weekly_km`. A user with `max_weekly_km=40` racing 50km gets `weekly_km=40`. The race itself is set independently in `distribute_week` so distance is correct, but the totals roll up wrong. Probably needs a phase-aware cap (don't apply user weekly cap to Race).
- **`compute_weekly_targets` Recovery elevation formula uses `prev_build_km * training_ratio`** (line 513) — i.e. derives recovery elev from prev build *km*, not from prev build *elev*. Not necessarily wrong (it normalizes through `training_ratio`), but a more direct formulation would be `prev_build_target.weekly_elev * recovery_elev_fraction`. Worth a coaching review.
- **`_intensity_for` has `if workout_type in ('rest',):`** — using a 1-tuple for a single-string check. Pure cosmetic, not worth a diff.
- **1490-line file size.** Layer 1-4 functions (`assign_phases`, `compute_weekly_targets`, `distribute_week`, `apply_key_sections`) plus the calendar/theme helpers and the constants block are all cohesive — splitting would break the "single source of truth" intent of the constants section. Keep as one file unless the constants get reused elsewhere.

---

### Session 5 — 2026-04-28 — Performance tracker

**Focus:** `backend/services/performance_tracker.py` (1224 lines) — second-largest service, no recent code-quality pass. Owns the dynamic star-plot pipeline: Strava stream ingestion, pace-grade curve fitting, fatigue-curve aggregation, and the achievements/PR detector.

**Files touched:**
- `backend/services/performance_tracker.py`
- `backend/tests/test_services/test_performance_tracker_audit.py` (new)

**Issues fixed:**

1. **Stream-cache poisoning on Strava failure (lines 360–375 backfill path, 415–428 main path).** `StravaService.download_streams` returns `{param: []}` (a *truthy* dict of empty lists) on transport error / non-200 response — see `services/strava_service.py:146,153`. The performance tracker treated that as a successful download, immediately calling `cache_service.cache_streams(...)` which writes the empty payload to both filesystem JSON and the `StravaActivity.streams` DB column. From that point forward, `get_cached_streams` returns the truthy-but-empty dict, so the activity is *permanently* useless to curve fitting (even after Strava recovers) — the `if streams:` guard around the append-to-list path doesn't catch it because the dict is non-empty. Added `_streams_have_data()` helper that requires at least one non-empty list among the values, and gated both the cache write and the append on it. **Real, silently-degrading bug** that affects every snapshot calculation any time Strava blips.
2. **`compare_periods` ZeroDivisionError (line 659).** `'flat_pace_pct': ((s1.flat_pace - s2.flat_pace) / s2.flat_pace) * 100` had no zero/None guard, while the per-grade loop right below it (line 671) already had a `if pace2 > 0 else 0` guard. A `flat_pace = 0` snapshot (degenerate but possible — e.g. corrupted JSON column or a future bug elsewhere setting it to 0) crashes the dashboard. Added the matching guard.
3. **`compare_periods` None-anchor crash (lines 663–666).** `anchor1 = snapshot1.anchor_ratios; for grade_str in anchor1.keys()` raised `AttributeError: 'NoneType' object has no attribute 'keys'` if the JSON column was null. Same in `_check_personal_record` at line 868. Coalesced both to `or {}`.
4. **Swallowed DB-fallback error (line 292) — `except Exception: pass`.** When the cached-activities path is empty, the code falls back to a `StravaActivity.query` over the period. A bad query (schema drift, db disconnect, …) was silently consumed, and the function moved on to the third fallback (Strava HTTP) without a single log line. Replaced with `logger.warning(...)` so ops can see it. Also dropped the redundant inline `from models import StravaActivity` (already imported at line 19).
5. **`award_achievements` no rollback on commit failure (lines 928–933).** The loop called `achievement_repo.create(achievement)` (each `flush()`-ing) and then a single trailing `commit()`. If the commit raised, the function returned the in-memory `new_achievements` list as if persisted, and the dirty session state would resurface on the next request's flush. Wrapped the create+commit in a `try/except` that calls `rollback()`, logs via `logger.exception`, and returns `[]`. Also early-return `[]` when there's nothing to commit so the empty-list branch can't accidentally fall through.
6. **N+1 DB scan in PR detection (lines 814–818, 873–875).** `detect_achievements` looped over the 7 `ANCHOR_GRADES`, each call to `_check_personal_record` independently hitting `performance_repo.get_grade_performances(user_id)` (a full table-scan returning every grade row for the user). Cost was ~7× per call, scaling with months of history. Pulled the query above the loop, partitioned the result into `perfs_by_grade: Dict[int, List[GP]]`, and threaded the matching slice into `_check_personal_record(..., all_grade_perfs=...)`. The signature stays backward-compatible (kwarg defaults to `None`, which keeps the old per-grade-query path for any other caller).

Also a cleanup picked up by ruff E712: `df["moving"] == True` → `df["moving"].astype(bool)` (line 1015). The original was correct only because `moving` happens to be bool-typed; the replacement is intent-explicit and ruff-clean.

**Verification:**
- `py_compile` clean.
- 8 new smoke tests in `tests/test_services/test_performance_tracker_audit.py`:
  - `_streams_have_data` rejects the empty failure payload, accepts a real one, rejects None / non-dict / `{}`.
  - `compare_periods` returns `flat_pace_pct == 0` instead of crashing when `s2.flat_pace == 0`.
  - `compare_periods` accepts `anchor_ratios=None` on both sides without `AttributeError`.
  - `award_achievements` calls `rollback()` and returns `[]` when `commit()` raises.
  - `award_achievements` short-circuits with no commit when `detect_achievements` returns `[]`.
  - `_check_personal_record` does not call `performance_repo.get_grade_performances` when the pre-filtered list is provided.
- Full backend test suite: **213 tests pass** (was 205 + 8 new). Same `fpdf` ignore as prior sessions: `pytest tests --ignore=tests/test_api/test_race_brief_pdf.py`.
- Ruff on the file: 10 errors (down from 12 baseline) — the 10 are all pre-existing `E402`/`F401` from the `sys.path.insert` shim that lets the file import from `data_analysis/predictor/`. None are new.

**Not changed (intentionally deferred):**
- **Lexical `isoformat()` comparison on `start_date` (lines 263, 306).** `period_start.isoformat()` produces `+00:00`-suffixed strings, while Strava cached activities carry `Z` suffixes. Char-by-char comparison happens to give the correct answer in every realistic case because the date prefix differs first, and within the same instant `Z` (0x5A) > `+` (0x2B) gives semantically correct boundary behavior. Fragile if Strava ever changes the format or if the cache is ever populated from a non-Strava source. Worth a follow-up pass that parses both sides into `datetime` and compares as objects.
- **Quarterly `period_end = period_start + timedelta(days=90)` (line 233).** Quarters are 89–92 days; this can drop boundary activities or double-count them between quarters. Documented as "Approximate" but worth a real fix that walks to the first day of the next quarter.
- **`sys.path.insert(0, ...)` import shim (lines 28–29).** Modifies global Python path on import, which produces all the `E402` ruff errors above. The "right" fix is to make `data_analysis/predictor/` an installed package; out of scope for an audit pass.
- **`_calculate_curve_from_streams` swallows mismatched stream lengths (lines 509–513).** `pd.DataFrame({...})` raises `ValueError` if the lists differ in length; there's no try/except around it, but `_aligned_stream_df` (used by the fatigue path) already handles this. Worth unifying both code paths around one helper.
- **`StravaActivity` model query in `get_activities_in_period` doesn't paginate.** Probably fine (per-user, per-period, low cardinality), but a user with 10k+ activities in a quarter could pull a lot of rows.

---

### Session 4 — 2026-04-28 — Stripe billing API

**Focus:** `backend/api/billing.py` (322 lines) — flagged in the backlog as security-sensitive (Stripe webhook handler). Owns checkout session creation, webhook delivery, and cancellation flow.

**Files touched:**
- `backend/api/billing.py`

**Issues fixed:**

1. **`cancel_subscription` immediately revoked premium access (line 250).** The endpoint correctly told Stripe `cancel_at_period_end=True` (so Stripe keeps billing+access until period end), but then locally set `sub.status = 'canceled'`. The model's `is_premium` requires `status == 'active'`, so the user lost premium gating instantly despite paying for the rest of the period. Fix: don't mutate `status` on cancel — only stamp `canceled_at`. The `customer.subscription.deleted` webhook (which Stripe fires when the period actually ends) already transitions `status='expired'` and `plan='free'`, so the lifecycle is correct without the eager flip. **This is a real, live billing bug visible to any paying user who clicked Cancel.**
2. **Race day pass webhook was not idempotent (line 276).** `_handle_checkout_completed` set `sub.expires_at = datetime.now(timezone.utc) + timedelta(days=7)`. Stripe webhook delivery is at-least-once; a redelivered `checkout.session.completed` event hours or days later would silently extend the user's pass window each time. Fix: anchor on `session['created']` (the Stripe-supplied session creation timestamp) so duplicate deliveries compute the same `expires_at`. Same anchor is used for `started_at` for symmetry. Module-level constant `RACE_DAY_PASS_DURATION = timedelta(days=7)` replaces the inline literal.
3. **`datetime.utcfromtimestamp(period_end)` (line 305).** Two problems: (a) deprecated in Python 3.12 — emits `DeprecationWarning` and is slated for removal; (b) returns a *naive* datetime, which would then be compared against `datetime.now(timezone.utc)` in `UserSubscription.is_premium` and raise `TypeError: can't compare offset-naive and offset-aware datetimes`. Switched to `datetime.fromtimestamp(period_end, tz=timezone.utc)` to match the rest of the codebase.
4. **`_handle_checkout_completed` accepted any string as `plan`.** A corrupted/spoofed metadata field (signature is verified upstream, but defense-in-depth) could write arbitrary strings into `sub.plan`, which downstream code keys off (`is_premium`, `_limits`, etc.). Added a `VALID_CHECKOUT_PLANS = {'premium_monthly', 'premium_yearly', 'race_day_pass'}` set and a guard that logs+returns early on unknown plans.
5. **`int(user_id)` could raise `ValueError` (line 270).** A non-numeric `metadata.user_id` would crash the handler, returning 500 to Stripe, which then retries the webhook indefinitely. Wrapped in `try/except (TypeError, ValueError)`, logging the offending value and returning early — Stripe sees a 200 and stops retrying a permanently-bad event.
6. **`stripe.Customer.create` (line 124-126) was outside the `try`/`except` block.** A Stripe-side hiccup or rate-limit on the customer create call would propagate as an uncaught exception, leaking a stack trace to the client and bypassing the friendly `"Failed to create checkout session"` error response. Moved customer creation inside the existing `try` block.

**Verification:**
- `py_compile` clean.
- Five targeted smoke tests written and passing:
  - `_handle_checkout_completed` rejects unknown plan (no DB writes).
  - `_handle_checkout_completed` rejects non-integer user_id (no DB writes, doesn't raise).
  - `_handle_checkout_completed` for race_day_pass produces identical `expires_at` across two deliveries.
  - `_handle_subscription_updated` writes a tz-aware `expires_at`.
  - `cancel_subscription` source no longer contains `sub.status = 'canceled'`.
- Full backend test suite: **205 tests pass** (`pytest tests --ignore=tests/test_api/test_race_brief_pdf.py`; same `fpdf` ignore as prior sessions).
- Grep for `sub\.status\s*=\s*'canceled'` across `backend/` returns nothing — no orphaned callers.

**Not changed (intentionally deferred):**
- **No webhook event-id idempotency table.** A truly robust webhook handler stores `event['id']` and skips already-processed events. Today's fix (anchoring race-pass expiry on session.created) covers the obvious correctness hole, but `_handle_subscription_updated` and `_handle_subscription_deleted` are still re-processed on redelivery. Their writes happen to be naturally idempotent (set status/plan to fixed values), so the missing dedupe table doesn't currently cause divergence. Worth a session of its own once a `processed_webhook_events` table is in scope.
- **`current_period_end` may have moved in newer Stripe API versions** (2025-04-30+ moved it onto `items.data[].current_period_end`). The current code reads `subscription.get('current_period_end')` which works on older API versions; need to confirm what API version this account is pinned to before changing. File a backlog item.
- **`logger.info(f"Waitlist signup: ... email={email} ...")` (line 219) logs PII.** Probably fine for a private waitlist log, but flagging — depending on log retention/destinations this is a GDPR concern. Hash the email or drop it from the log if log retention >30d.
- **`requires_premium` dev-mode bypass** uses `os.environ.get('FLASK_ENV') == 'development'` — consistent with the rest of the codebase (see `services/agent/tool_handlers/training.py`, `api/training_plan.py`, `api/agent.py`). Standardizing on `current_app.debug` would be a project-wide refactor; out of scope.

---

### Session 3 — 2026-04-28 — Agent training tool handlers

**Focus:** `backend/services/agent/tool_handlers/training.py` — 1090-line file flagged in the backlog as the only place in `services/` that calls `db.session.commit()` directly. Houses 17 tool handlers that the LLM agent uses to read/write training plans, preferences, and route bindings.

**Files touched:**
- `backend/services/agent/tool_handlers/training.py`

**Issues fixed:**

1. **Transaction-boundary violation in `_handle_match_routes_to_plan`.** The handler called `match_routes_to_plan(plan, prefs)` (which mutates per-day route bindings) and then committed via a local `from database import db; db.session.commit()` wrapped in `except Exception: pass`. Two problems: (a) bypasses the repository's transaction layer (the `BaseRepository.commit/rollback` API exists exactly to keep this one place); (b) silently swallowed commit errors meant the handler returned `{'status': 'matched'}` even when persistence failed, leaving the user with an apparently-successful match that didn't actually save. Fix: keep a `plan_repo` reference (was instantiated inline as `TrainingPlanRepository().find_one_by(...)`), call `plan_repo.commit()`, and on failure roll back, log via `logger.exception`, and return an error so the caller sees the failure.
2. **Silent-data-loss inline elevation-gain duplicate in `_handle_inspect_training_plan`.** A 6-line inline loop computed elevation gain using only `point.get('elevation', 0)`, treating missing elevations as 0 (which would cause a huge bogus negative diff against the previous real elevation). The canonical `_compute_gpx_elevation_gain` helper (already imported on line 14, already used elsewhere in this file at line 236) handles both `'ele'` and `'elevation'` keys and properly skips points with no elevation by carrying forward `prev_ele`. Replaced the inline loop with the helper. Real correctness fix for any GPX whose first/intermediate points lack elevation, or whose elevation key is `'ele'` (which is what the standard GPX 1.1 schema actually emits).
3. **Two `except Exception: pass` blocks (lines 237, 311) silently dropped GPX-load errors** when resolving race-target distance/elevation in `_handle_generate_training_week`. The fall-through behavior (race_dist_km/race_elev_m staying at default) is acceptable, but losing diagnostic info hides a real signal — a user who repeatedly hits a corrupted GPX would never see why their plan generation lacks race targets. Replaced both with `logger.warning(...)`.
4. **`__import__('datetime').timedelta(weeks=weeks)` on line 49.** Bizarre — `timedelta` is already imported at the module top (`from datetime import datetime, timedelta, timezone`). Replaced with `timedelta`. Pure cleanup, but the kind of artifact that looks like there's a hidden reason and slows readers down.
5. **Dead variable `tw` (line 192).** `tw = total_weeks_param or len(valid_weeks)` was computed but never referenced — `_inject_calendar_dates` is called with just `valid_weeks, race_date`. Removed.
6. **Redundant local imports of `GPXFileRepository` (lines 229, 302) and `_compute_gpx_elevation_gain` (line 303).** Both are already imported at module top (lines 8 and 14). Deleted.

**Verification:**
- `py_compile` clean.
- `pytest backend/tests/test_agent/test_tool_handlers.py` — **28 passed** (covers `_handle_*` validation + impact-assessment paths).
- Full backend test suite: **205 tests pass** (`pytest backend/tests --ignore=backend/tests/test_api/test_race_brief_pdf.py`; same `fpdf` ignore as prior sessions).
- Final grep for `db\.session\.|__import__|except: pass` against the file returns nothing.

**Not changed (intentionally deferred):**
- `_handle_save_training_plan` and `_handle_adjust_training_week` already use the repo's `.commit()` correctly — no change needed.
- `_handle_save_training_preferences` calls `repo.upsert(user_id, clean)` then `repo.commit()` — also correct.
- 1090-line file size: `_handle_start_onboarding_questionnaire` (95 lines of nested wizard schema) and `_handle_inspect_training_plan` (200 lines of plan-quality warnings) are obvious candidates to split into `wizard_schema.py` and `plan_inspection.py`. Out of scope for a code-quality pass; would be a refactor.
- `_session_validated_weeks`, `_session_race_targets`, `_session_plan_warnings` are module-level dicts used as per-user caches. Not thread-safe and not bounded — if the agent server runs multi-threaded these could leak across requests. Worth a session of its own; the pattern is repeated in other tool-handler modules.
- `_handle_get_training_history` uses `__import__` in pre-fix code; the rest of the function is fine.
- `_handle_adjust_training_week` line 828 has a long `VALID_TYPES` set duplicated against `VALID_WORKOUT_TYPES` imported on line 15. Could consolidate, but they're not identical (the local one omits some valid types and includes `'strength'`). Worth a coaching-rules audit to confirm intent before merging.

---

### Session 2 — 2026-04-28 — Hybrid prediction dispatcher

**Focus:** `backend/services/hybrid_prediction_service.py` — the central tier router that combines physics + ML residual corrections. High-value to keep clean since every prediction flows through it.

**Files touched:**
- `backend/services/hybrid_prediction_service.py`

**Issues fixed:**

1. **Training-serving skew on `prev_pace_ratio` feature.** `_build_ml_features` hardcoded `v_flat_pace = (1000 / 3.33) / 60` (~5.0 min/km) when computing `current_pace_ratio = pace_min_km / v_flat_pace`. The training pipeline (`data_analysis/predictor/ml_residual.py:182,259`) divides by the user's *actual* `flat_pace`, so a runner whose calibrated `v_flat` is 4.0 m/s (~4.17 min/km) had a `prev_pace_ratio` ~20% lower than the model was trained against. This directly contradicted the function's own docstring ("Computes real values for all features to match the training pipeline, avoiding training-serving skew from placeholder values"). Fix: added a `flat_pace_min_km` kwarg to `_build_ml_features` and plumbed it from `_predict_tier3` using `learned_params['v_flat']`. Default fallback preserved for callers that don't have calibrated params.
2. **Asymmetric CI multiplier cap.** The lower-bound multiplier was clamped via `lower_mult = max(0.5, lower_mult)` and the corrected pace was clamped to `[0.5, 2.0]`, but the *upper*-bound multiplier was never clamped. With high `effective_variance` and a positive `effort_adjustment`, the upper CI could exceed 2× flat pace — well past the operational range used elsewhere. Added a symmetric `upper_mult = min(2.0, upper_mult)`.
3. **Misleading dead comment.** Block above `physics_result['segments'] = corrected_segments` claimed to "Rebuild aggregated segments for display (200m to larger groups)" — but no rebuild happened, the comment trailed off with "For simplicity, use the existing segments structure". Removed; the assignment speaks for itself.
4. **Pointless `ci_lower`/`ci_upper` aliasing** of `ci_lower_time`/`ci_upper_time`. Inlined.
5. **Dev scratch comments removed:** trailing `# Need to pass this explicitly now…` / `# New k_up arg` (×2) on `predict_downhill_velocity` calls, and a 7-line meta-commentary block above the `predict_residual_corrections` call inside `generate_model_comparison`. They didn't describe code behavior — they were notes-to-self from when the function was being written.

**Verification:**
- `py_compile` clean.
- Direct unit-style smoke test of `_build_ml_features` (with stubs for repo/service deps): default fallback returns `prev_pace_ratio[1] = 0.799` (≈ pace / 5.0 min/km); calibrated path with `flat_pace_min_km=4.0` returns exactly `1.0` for an at-flat segment; zero/None falls back to default.
- Full backend test suite: **205 tests pass** (`pytest tests/ --ignore=tests/test_api/test_race_brief_pdf.py`; same `fpdf` ignore as last session).

**Not changed (intentionally deferred):**
- `_predict_tier1` ignores its `effort` parameter (Tier 1 has no effort adjustment). The docstring already says so. Could remove the parameter, but it's used uniformly across the three tier methods for caller-side symmetry — net: leave it.
- Repeated `count_for_user` DB calls (each tier method calls it once after `_determine_tier`/`_validate_force_tier` already called it). Real but minor; would require threading the count through `_determine_tier`'s return value.
- `_build_ml_features` always uses default weather (15°C/50%/no wind) when called from `_predict_tier3`. Could be intentional if route weather isn't trusted at prediction time, but worth a follow-up to confirm with whoever owns that flow.
- `generate_model_comparison` synthetic segments use `prev_pace_ratio: 1.0` (line 767). Not a bug — it's a theoretical curve at fixed conditions — but worth noting the same skew issue would apply if these segments were ever used for a real user prediction.

---

### Session 1 — 2026-04-28 — Strava ingestion + GPX parser

**Focus:** Data ingestion path for Strava + GPX. Hot path on every login and upload.

**Files touched:**
- `backend/services/strava_service.py`
- `backend/services/strava_sync_service.py`
- `backend/services/cache_service.py`
- `backend/services/gpx_parser.py`

**Issues fixed:**

1. **`strava_service.py` — Missing HTTP timeouts (4 call sites).** `requests.get/post` with no `timeout=` can hang the calling thread indefinitely on a slow/dead Strava endpoint, leaking the background sync thread. Standardized to `timeout=30` to match `osm_terrain_service.py`/`route_generation_service.py`.
2. **`strava_service.py` — `download_streams` made N HTTP calls instead of 1.** The Strava streams endpoint accepts a comma-separated `keys` list. Fetching 8 keys one at a time used 8x the rate-limit budget and 8x the latency. Replaced with a single batched request.
3. **`strava_service.py` — `get_auth_url` did manual query-string concat without URL encoding.** A `state` value containing `&` or `=` (or any reserved character) would corrupt the auth redirect. Switched to `urllib.parse.urlencode`.
4. **`strava_service.py` — `get_timestamp_for_last_year` used naive local time.** `datetime.now()` without a tz; converting via `.timestamp()` is locale-dependent. Switched to `datetime.now(timezone.utc)`.
5. **`strava_sync_service.py` — Bare `except:` swallowed BaseExceptions** (line 149). Replaced with `except Exception` and logged the error so future failures aren't invisible.
6. **`strava_sync_service.py` — `create_app()` called twice on error path.** The error handler re-built the Flask app to write the error status. Reused the existing `app` from the outer `with app.app_context():` instead — saves ~1s on every sync failure and avoids initializing the DB engine twice.
7. **`strava_sync_service.py` — Redundant `min(50, len(...))` slice.** `list[:50]` already handles short lists. Simplified.
8. **`strava_sync_service.py` — `limit` parameter shadowed.** Documented as "max top activities to download" but never used (hardcoded to 50). Removed the unused parameter.
9. **`cache_service.py` — `open()` without `encoding='utf-8'`.** JSON read/write defaulted to platform encoding (cp1252 on Windows). Pinned to UTF-8 on both read and write.
10. **`cache_service.py` — `streams_dir.mkdir(exist_ok=True)` without `parents=True`.** Worked only because the parent was created on the prior line; brittle if the order is ever swapped. Added `parents=True` for symmetry/safety.
11. **`gpx_parser.py` — Case-sensitive `.gpx` suffix check.** A file named `route.GPX` would be rejected. Switched to `suffix.lower()`.
12. **`gpx_parser.py` — `open()` without UTF-8 encoding + uninformative errors.** GPX is XML and should be UTF-8. Error messages didn't include the offending path. Both fixed.

**Verification:**
- All 4 modified modules import cleanly.
- `py_compile` on all 4 files: OK.
- Targeted smoke tests with `unittest.mock`:
  - `get_auth_url` correctly URL-encodes a state value containing `&` and `=`.
  - `get_timestamp_for_last_year` returns ~365 days back in UTC.
  - `download_streams` makes exactly 1 HTTP call (was 8), batches the `keys` param, hands `timeout=30`, and returns full empty dict on 404 / `ConnectionError`.
  - `parse_gpx_file` accepts uppercase `.GPX`, parses UTF-8 unicode (`Caffè Püppi`) correctly, and includes the offending path in `FileNotFoundError`/`ValueError`.
- Full backend test suite: **205 tests pass** (`pytest backend/tests --ignore=tests/test_api/test_race_brief_pdf.py`, the ignore was for `fpdf` not being installable in the sandbox; unrelated to the changed code).

**Not changed (intentionally deferred):**
- Path-traversal hardening for `cache_service.get_stream_cache_path` — `user_id` is currently always an int from the auth context, so no live risk. Note for future if the type guarantee weakens.
- Strava rate-limit handler — the project lacks a centralized 429 backoff. Worth a session of its own.
- `_sync_user_background` re-instantiates all 4 repositories on entry. Acceptable for now (each thread needs its own session-bound repo) but could be pushed into a context manager.

---

## Backlog (prioritized)

### High impact

- [ ] **Centralized Strava rate-limit handling.** No 429 retry/backoff anywhere. A burst sync can blow the 100/15min limit and silently fail. Suggested: a single `_request()` helper in `StravaService` that handles `Retry-After` + exponential backoff.
- [x] ~~**`backend/services/agent/tool_handlers/training.py` (1090 lines)** — only place in `services/` that calls `db.session.commit()` directly (line 1082) instead of going through a repo.~~ Done in Session 3 (6 fixes including the direct-commit violation, an elevation-gain helper mismatch, and silent-error logging gaps).
- [x] ~~**`backend/services/plan_engine.py` (1490 lines)** — largest service; check cohesion + dead code. Likely splits into a few smaller modules.~~ Done in Session 6 (5 fixes including 2 real correctness bugs in `apply_key_sections` — descent annotation leaking across weeks, and `theme == 'Base'` always-false comparison silently giving Base hill repeats Build-week intensity).
- [x] ~~**`backend/services/performance_tracker.py` (1224 lines)** — second largest service, no recent code-quality pass.~~ Done in Session 5 (6 fixes including a real cache-poisoning bug on Strava failures, a ZeroDivisionError on dashboard compare, and an N+1 query in PR detection).
- [x] ~~**`backend/services/hybrid_prediction_service.py` (816 lines)** — the central prediction dispatcher; high-value to keep clean.~~ Done in Session 2 (4 fixes including a real training-serving skew bug).

### Medium impact

- [ ] Audit all `except Exception as e:` blocks (106 of them) for over-broad catches that mask real bugs. Many likely could be narrower (`requests.RequestException`, `ValueError`, etc.).
- [ ] `frontend/src/stores/` — Pinia stores: any unhandled promise rejections, race conditions on parallel fetches?
- [x] ~~`backend/api/billing.py` (322 lines) — Stripe webhook handler is security-sensitive; verify signature checking and idempotency.~~ Done in Session 4 (6 fixes including a real billing bug — `cancel_subscription` was revoking premium access immediately instead of at period end, and race day pass duplicate webhooks were silently extending pass expiry).
- [x] ~~`backend/api/training_plan.py` (520 lines) — largest API blueprint; check for missing input validation.~~ Done in Session 7 (8 fixes including a real correctness bug — stringy `distance_km` PATCH crashed week-totals sum() and persisted the corruption — and a real header-injection vector in `export_ics` Content-Disposition).
- [ ] `data_analysis/predictor/train.py` — model training script; check for data leakage in train/val split.

### Lower impact / chores

- [ ] Replace remaining `print(...)` calls in `backend/manage.py` with `logger.info` — minor, only affects CLI UX.
- [ ] Standardize timezone handling: many services use `datetime.now(timezone.utc)`, but a few might still slip through. Run the grep above periodically.
- [ ] `backend/services/gpx_parser.py` — does not parse `gpx.routes` (only `tracks` and `waypoints`). Probably OK for runners but could miss data on some imports. File a feature flag question, not a bug.
- [ ] `services/cache_service.py` — `clear_stale_caches` doesn't delete the on-disk JSON, only the DB row. Disk grows unboundedly.

### New findings to investigate next session

- [ ] **Per-user module-level caches in `tool_handlers/training.py`** (`_session_validated_weeks`, `_session_race_targets`, `_session_plan_warnings`). Not thread-safe and not bounded; under multi-threaded Flask they can leak across requests. Same pattern likely repeated in other tool-handler modules — grep `_session_` across `services/agent/tool_handlers/` and audit holistically.
- [ ] **`tool_handlers/training.py` `VALID_TYPES` (line 828) duplicates `VALID_WORKOUT_TYPES` (imported line 15)** but with subtle differences (omits some, includes `'strength'`). Need a coaching-rules audit to confirm whether one is the truth and the other should be deleted.
- [ ] **`tool_handlers/training.py` size (1090 lines)**: `_handle_start_onboarding_questionnaire` and `_handle_inspect_training_plan` are obvious split candidates — `wizard_schema.py` and `plan_inspection.py`. Refactor, not audit-scope.
- [ ] `services/strava_sync_service.py` `_sync_user_background` runs in a daemon thread spawned via raw `threading.Thread`. If the user kicks off a sync and the process is restarted (Gunicorn worker recycle), the thread dies mid-flight and `sync_status` is left in `'syncing'`. Suggest a janitor that resets stuck rows older than N minutes, or move to a real task queue.
- [ ] `services/strava_service.py` `download_streams` returned an empty list per stream on non-200 (`else: streams_data[param] = []`). After the batched-request fix, the single failure now means the whole call returns empty streams — verify downstream handles that the same way it handled per-stream empties.
- [ ] `services/hybrid_prediction_service.py:_predict_tier3` always builds ML features with default weather (15°C/50%/no wind) and no terrain factors. Confirm this is intentional vs. a missed plumbing — if the system has weather/terrain enrichment elsewhere, this drops it on the floor.
- [ ] `services/hybrid_prediction_service.py` calls `count_for_user` 2x per prediction (once in `_determine_tier`/`_validate_force_tier`, once in the tier method for metadata). Cheap, but trivially fixable by threading the count through the return value.
- [ ] **`backend/api/billing.py` webhook event-id idempotency.** Today's session anchored race_day_pass expiry on `session.created`, which prevents the most damaging duplicate-delivery bug, but `_handle_subscription_updated`/`_handle_subscription_deleted` are still re-processed on every redelivery. Add a `processed_webhook_events(event_id, processed_at)` table and short-circuit at the top of `stripe_webhook` before dispatch.
- [ ] **`backend/api/billing.py` Stripe API version drift.** `_handle_subscription_updated` reads `subscription.get('current_period_end')`. In Stripe API 2025-04-30+ this field moved to `items.data[].current_period_end`. Confirm the account's pinned API version before this drifts.
- [ ] **`backend/api/billing.py` PII in logs.** `join_waitlist` logs email at INFO level (line 219). Consider hashing or dropping depending on log retention.
- [ ] **`services/performance_tracker.py` lexical ISO comparison.** `start_date` cached strings end in `Z`, `period_start.isoformat()` ends in `+00:00`. Char-compare happens to work today; parse to `datetime` for safety. Lines 263, 306.
- [ ] **`services/performance_tracker.py` quarterly period overshoot.** `period_end = period_start + timedelta(days=90)` (line 233) can clip Q1 (90 days) and overshoot Q3/Q4 (92). Compute the first day of the next quarter instead.
- [ ] **`services/performance_tracker.py` `sys.path.insert` import shim** (lines 28–29) — modifies global Python path on import. Make `data_analysis/predictor/` an installable package and remove the shim.
- [ ] **`services/performance_tracker.py` `_calculate_curve_from_streams` no length-alignment guard** (lines 509–513) — the fatigue path already handles this via `_aligned_stream_df`. Unify both paths.
- [ ] **Cache poisoning at the source.** The fix in Session 5 only protected `performance_tracker.py`. Any other caller of `cache_service.cache_streams(...)` paired with `strava_service.download_streams(...)` has the same risk. Better fix: have `download_streams` return `None` instead of `{param: []}` on failure, and update all callers. Grep `download_streams` to find them.
- [ ] **`plan_engine.py` Peak/Build floor drift after 10% cap.** Lines 485-494 cap weekly_km at +10% over the previous non-recovery week; lines 537-543 only re-enforce `WEEKLY_MIN_LR_MULTIPLIER = 1.6`. So Peak weeks whose pre-cap target was at the `PEAK_MIN_LR_MULTIPLIER = 1.7` floor and got trimmed will settle at 1.6×LR instead of 1.7×LR. Same issue for Build (2.0× → 1.6×). Coaching-rules decision before fixing.
- [ ] **`plan_engine.py` Race-week volume capped below race distance.** Line 481 sets `weekly_km = RACE_WEEK_EXTRA_KM + race_distance_km`, then line 533 hard-caps to `max_weekly_km`. A user with `max_weekly_km=40` racing 50km gets a 40km Race week. Probably want phase-aware cap exemption for `phase == 'Race'`.
- [ ] **`plan_engine.py` Recovery elevation derived from km × training_ratio.** Line 513 computes `weekly_elev = prev_build_km * training_ratio * recovery_elev_fraction` instead of using the previous build week's *actual* elevation. Works because of the ratio normalization but is a more confusing formulation than necessary. Refactor to `prev_build_target.weekly_elev * recovery_elev_fraction`.
- [ ] **`api/training_plan.py` weeks JSON schema validation.** Session 7 added type checks but a caller can still PUT `weeks=[{"garbage": "values"}]` and corrupt the dashboard. A jsonschema (or pydantic) validation pass on `weeks`, `days[]`, and `steps[]` would close the rest of the gap. Cross-cutting — also affects the agent's `_handle_save_training_plan` path.
- [ ] **`api/training_plan.py:get_dashboard` `prediction_repo.get_latest_for_gpx` not guarded.** Line 230 — a DB hiccup there 500s the entire dashboard. Lower priority than the `training_load` suppression (single query, unlikely to fail mid-request) but defensively wrap in try/except + log for parity.

---

## Conventions

- **Branch:** Stay on the audit branch listed in **Status** for the current session. Don't fork.
- **Commit messages:** `chore(audit): <area> — <n> fixes`. List the fixes in the body, one bullet each.
- **Scope:** One focus area per session. Resist the urge to "while I'm here" into adjacent files — note them in the backlog instead.
- **Tests:** Run what's runnable in the current environment. Note clearly when full suite couldn't run (deps, DB, network).

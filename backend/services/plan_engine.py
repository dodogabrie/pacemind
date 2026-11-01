"""Constraint-based training plan generator.

Deterministic engine that produces physically valid training plans from
athlete data and race parameters. The pipeline is a small number of pure
functions chained by ``generate_plan``:

    assign_phases          -> list[str]          (Layer 1: macro periodization)
    compute_weekly_targets -> list[WeekTarget]   (Layer 2: weekly volume / D+)
    distribute_week        -> list[dict]         (Layer 3: daily placement + sizing)
    apply_key_sections     -> list[dict] mut.    (Layer 4: race-profile titles)

Every layer is independent and side-effect-free except for in-place title
edits in Layer 4. Constants, phase rules and workout profiles are declared
up-front so each layer is small enough to read in one screenful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Days
# ---------------------------------------------------------------------------

DAYS_OF_WEEK = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
                'Saturday', 'Sunday']
DAY_INDEX = {d: i for i, d in enumerate(DAYS_OF_WEEK)}
MIDWEEK_DAYS = frozenset(('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'))


def _day_offset(day_name: str) -> int:
    return DAY_INDEX.get(day_name, 0)


def _day_distance(a: str, b: str) -> int:
    """Cyclic distance between two day names (0..3)."""
    d = abs(_day_offset(a) - _day_offset(b))
    return min(d, 7 - d)


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

VALID_PHASES = ('Base', 'Build', 'Peak', 'Recovery', 'Taper', 'Race')

# Workout taxonomy --------------------------------------------------------
# ``descent_session`` is a controlled-downhill workout with eccentric load
# (4-6 reps of 200-400m vert descents). Coaching consensus (Vert.run, Koop,
# Roche) prescribes 1 session/2 weeks in Build and 1/week in Peak for races
# with significant D- (≥ 1500 m). Eccentric work is hard but not maximal —
# treated as hard for spacing, mountain-eligible for placement.
HARD_WORKOUTS = ('intervals', 'hill_repeats', 'vert_session', 'tempo',
                 'descent_session', 'uphill_intervals')
EASY_WORKOUTS = ('easy', 'recovery')
MOUNTAIN_WORKOUTS = ('hill_repeats', 'vert_session', 'descent_session')
# uphill_intervals is intentionally NOT in MOUNTAIN_WORKOUTS: it's the
# race-type-aware downgrade for VK / uphill_only when no mountain day is
# available, so it must be placeable on rolling / mid-week training days.
# It still carries climbing density (~35 m/km) via WORKOUT_DENSITY_CAP.


def _needs_mountain_day(workout: str, phase: str) -> bool:
    """Whether ``workout`` must be placed on a mountain-eligible calendar day.

    Base hill_repeats (~80 m D+ sprints) are exempt: they fit on any
    terrain so the placer can use any training day. Budget enforcement
    still uses ``MOUNTAIN_WORKOUTS`` membership directly so users that ask
    for zero mountain access still see the workout downgraded.
    """
    if workout not in MOUNTAIN_WORKOUTS:
        return False
    if phase == 'Base' and workout == 'hill_repeats':
        return False
    return True


# Easy/recovery/tempo days carry pseudo-elevation that we'd rather pour onto
# climb-focused days. Tempo intentionally absent: tempo on a long-run week is
# the rolling carrier for race-specific D+.
#
# Mountain plans (terrain_profile='mountain') tighten the eligible set: only
# easy_pickups / easy_strides / recovery flatten — plain ``easy`` keeps its
# natural rolling D+ so the weekday climb stimulus survives. Vert.run, Koop
# ("Chasing Vert"), Roche all converge on the rule "every weekday run on a
# mountain plan should carry some climb (200–300 m per session)" — without
# this, ~88 % of weekly D+ concentrates on Sat+Sun (issue #35).
ELEV_FLATTEN_TYPES = ('easy', 'easy_pickups', 'easy_strides', 'recovery')
ELEV_FLATTEN_TYPES_MOUNTAIN = ('easy_pickups', 'easy_strides', 'recovery')
# Targets for redistributed elevation. long_run is intentionally NOT here;
# saved D+ from flat easy days must not pile onto an already-loaded weekend.
ELEV_SINK_TYPES = ('hill_repeats', 'vert_session', 'race_simulation')

# When mountain access blocks a mountain workout, swap to a flat replacement.
# Used as the default fallback when a phase-specific downgrade isn't defined.
# descent_session has no flat equivalent — it falls back to easy.
#
# vert_session is sustained Z2-Z3 climbing (60-90 min). Without mountain
# access the closest flat substitute is a long tempo (Z3 metabolic stimulus
# of similar duration). Falling back to ``easy`` (the previous default) was
# silently killing the only hard session in mountain-budget-constrained
# Peak weeks (coach-review #3) — Vert.run, Koop, Magness all converge on
# "preserve the intensity tier, sacrifice the specificity tier".
MOUNTAIN_DOWNGRADE = {
    'hill_repeats': 'intervals',
    'vert_session': 'tempo',
    'descent_session': 'easy',
}

# Race-type-aware override. For VK / uphill_only races, a flat tempo or flat
# intervals downgrade trains the wrong metabolic system at the wrong muscular
# pattern (Vert.run / Suunto / Lavedrine 2024: every hard session for an
# all-uphill race must preserve climbing specificity, even when the calendar
# pushes it onto rolling terrain). ``uphill_intervals`` is a Z3 climbing
# threshold session sized at ~35 m/km — preserves the intensity tier AND the
# uphill recruitment pattern. Coach-review #43, #44.
MOUNTAIN_DOWNGRADE_BY_RACE_TYPE = {
    'uphill_only': {
        'hill_repeats': 'uphill_intervals',
        'vert_session': 'uphill_intervals',
        'descent_session': 'easy',  # no climbing analogue for descents
    },
}

# Intensity sessions on flat / rolling terrain. Coaching consensus
# (Vert.run, Jason Koop, iRunFar): tempo is a metabolic stimulus and
# belongs on flat ground — uphill tempos turn into strength work, not
# threshold. Intervals follow the same logic in Base/Build (engine
# building) and switch to uphill in Peak for race-specificity.
FLAT_INTENSITY_PHASES_INTERVALS = ('Base', 'Build')
FLAT_INTENSITY_DENSITY_CAP = 8.0     # m D+ / km — gentle rolling at most
FLAT_INTENSITY_MULTIPLIER = 0.20


def _is_flat_intensity(workout_type: str, phase: str) -> bool:
    """Whether tempo / intervals are prescribed on flat-rolling terrain
    for this phase. Hill_repeats and vert_session always carry the
    uphill stimulus and are unaffected."""
    if workout_type == 'tempo':
        return True
    if workout_type == 'intervals':
        return phase in FLAT_INTENSITY_PHASES_INTERVALS
    return False


def _is_flat_prescription(
    workout_type: str, phase: str, km: float, elev: float,
) -> bool:
    """Day-aware version of ``_is_flat_intensity``: returns True when the
    actual prescribed (km, elev) belongs in the flat-intensity bucket.

    Covers two cases:
      - Phase-driven flat sessions (``_is_flat_intensity`` is True).
      - Peak intervals that the placer was forced to drop on a flat day
        (mountain_days too narrow). Without this the title would
        promise "Z4 uphill" while D+ rounds to 0 — a coaching lie.
    """
    if _is_flat_intensity(workout_type, phase):
        return True
    if workout_type == 'intervals' and phase == 'Peak':
        if km <= 0:
            return True
        return elev / km <= FLAT_INTENSITY_DENSITY_CAP
    return False


def _downgrade_target(
    workout: str, phase: str, current: list[str],
    *, race_type: str = 'loop',
) -> str:
    """Pick a phase-appropriate downgrade for a mountain workout that can't fit.

    - Base: always 'easy'. The phase is aerobic-only by design; falling back
      to ``intervals`` would inject Z3+/Z4 stress that doesn't belong here.
    - Build/Peak: the canonical MOUNTAIN_DOWNGRADE *unless* it duplicates a
      workout already in ``current`` (typically tempo or intervals already
      taken). When duplicated we walk the hard-tier fallback chain — try
      the OTHER hard workout before collapsing to ``easy`` — so a Peak week
      losing its vert_session to a mountain-budget constraint still keeps
      one hard session (coach-review #3 — Vert.run, Magness "preserve the
      intensity tier").
    - ``race_type``-aware: for VK / uphill_only races, the canonical
      flat-tempo / flat-intervals fallback is replaced by ``uphill_intervals``
      (rolling-terrain Z3 climbing threshold) so the downgrade preserves
      both the intensity tier AND the uphill recruitment pattern
      (coach-review #43, #44).
    """
    if phase == 'Base':
        return 'easy'
    table = MOUNTAIN_DOWNGRADE_BY_RACE_TYPE.get(race_type, MOUNTAIN_DOWNGRADE)
    canonical = table.get(workout, MOUNTAIN_DOWNGRADE.get(workout, 'easy'))
    if canonical not in current:
        return canonical
    # Canonical fallback duplicates an existing workout. Try the alternate
    # hard option before degenerating to 'easy', so the downgrade preserves
    # the hard intensity tier whenever possible.
    if race_type == 'uphill_only':
        # All VK downgrades funnel to uphill_intervals; if it's already taken
        # there is no alternate hard slot that preserves climbing specificity.
        return 'easy'
    hard_alternates = {'tempo': 'intervals', 'intervals': 'tempo'}
    alternate = hard_alternates.get(canonical)
    if alternate and alternate not in current:
        return alternate
    return 'easy'

# ---------------------------------------------------------------------------
# Density caps
# ---------------------------------------------------------------------------

MAX_ELEV_DENSITY = 80.0          # absolute cap (m D+ / km)
FLAT_CITY_ELEV_DENSITY = 5.0     # gentle urban undulation
MIN_MEANINGFUL_ELEV_DENSITY = 10.0  # below this, snap easy/recovery to flat

# Coaching granularity for prescribed elevation. Trail-running plans don't
# meaningfully distinguish between 144 m and 156 m of D+. Step is 50 m, but
# the minimum non-zero prescription is 100 m — anything that would round to
# 50 m snaps to 0 ("treat as flat").
ELEV_ROUND_STEP = 50.0
ELEV_MIN_NONZERO = 100.0

# Coaching granularity for prescribed distance. Round to even km for every
# workout except the long run / race simulation, which are calibrated
# targets and stay at 0.1 km precision.
KM_ROUND_STEP = 2.0
KM_PRECISE_TYPES = ('long_run', 'race_simulation')


def _round_elev(elev: float) -> float:
    """Round D+ to coaching granularity. 0 stays 0, otherwise the result
    is 0 or a multiple of 50 ≥ 100. 50 m is intentionally never produced."""
    if elev <= 0:
        return 0.0
    rounded = float(int((elev + ELEV_ROUND_STEP / 2) // ELEV_ROUND_STEP)
                    * ELEV_ROUND_STEP)
    return rounded if rounded >= ELEV_MIN_NONZERO else 0.0


def _round_km(km: float, workout_type: str) -> float:
    """Round distance to the nearest even km (step 2 km). long_run and
    race_simulation are precise targets and pass through unchanged."""
    if workout_type in KM_PRECISE_TYPES:
        return round(km, 1)
    if km <= 0:
        return 0.0
    return float(int((km + KM_ROUND_STEP / 2) // KM_ROUND_STEP) * KM_ROUND_STEP)

# Per-workout density ceilings that override the multiplier when the race
# ratio is mountainous. Stops "Z3 tempo at 49 m/km" or "easy at 67 m/km" bugs.
WORKOUT_DENSITY_CAP = {
    'easy':            30.0,
    'easy_pickups':    25.0,
    'easy_strides':    20.0,
    'recovery':        20.0,
    'tempo':           25.0,
    'intervals':       35.0,
    'descent_session': 80.0,  # high D+ to set up descents
    # uphill_intervals: rolling-terrain Z3 climbing threshold (4-5 × 6 min
    # uphill). Cap at 35 m/km matches a 10 km / 350 m sustained-climb
    # session — coaching-typical for VK Build/Peak when the calendar
    # forces the workout off true mountain terrain (coach-review #43).
    'uphill_intervals': 35.0,
}

# Cap on midweek (Mon–Fri) workout elevation by terrain profile.
# Easy-day cap only (coach-review #111): structured sessions keep their profile
# D+ (HILL_REPEATS_PROFILE / DESCENT_SESSION_PROFILE) and treadmill days are
# limited by the machine incline instead (``_apply_treadmill_limits``).
MIDWEEK_CAP_EXEMPT = ('descent_session', 'hill_repeats', 'vert_session')
MIDWEEK_ELEV_CAP = {'flat_urban': 50, 'rolling_hills': 200, 'mountain': None}

# Race-week pre-race elevation density cap (m D+ / km). All shakeout days in
# the 6 days before race day must stay near-flat — eccentric load from rolling
# / hilly easy runs in race week causes residual quad damage that taper science
# explicitly avoids (Mujika & Padilla 2003 Sports Medicine review; Bosquet et
# al. 2007 Med Sci Sports Exerc meta-analysis: "preserve frequency, cut volume,
# MAINTAIN intensity" — but eccentric muscle damage is the one thing to also
# minimize). Without this cap a mountain-race week landed at 30 m/km easy days
# = 250 m D+ on Mon and Tue alone, ~500 m of pre-race eccentric load
# (coach-review #5).
RACE_WEEK_DENSITY_CAP = 10.0


# ---------------------------------------------------------------------------
# Workout profiles
# Single source of truth for distance ranges, elevation behaviour and
# recovery cost. Keeps placement / sizing helpers small.
# ---------------------------------------------------------------------------

# Distance range (km) for non-long-run workouts.
# Minimum 8 km on every running session — anything shorter is barely
# warm-up + cool-down for trail running and isn't a useful stimulus.
# Exception: easy_strides (race-week shakeout) intentionally short.
WORKOUT_KM_RANGE = {
    'hill_repeats':    (8, 12),
    'vert_session':    (10, 15),
    'descent_session': (10, 14),
    'intervals':       (8, 12),
    'uphill_intervals': (8, 12),
    'tempo':           (8, 14),
    'easy':            (8, 12),
    'easy_pickups':    (8, 10),
    'easy_strides':    (4, 6),    # race-week shakeout, intentional exception
    'recovery':        (8, 10),
    'long_run':        (0, 0),
    'rest':            (0, 0),
    'race_simulation': (0, 0),
    'strength':        (0, 0),
}

# Race-week per-workout km range overrides. Lowered minimums (5 km for easy /
# recovery / easy_pickups) preserve frequency in the pre-race week within a
# tight budget: a 5 km easy is short enough to sit in 30 km / 4-5 sessions
# without overshooting, yet long enough to be a real shakeout. With the
# regular 8 km minimum, race-week easy days don't fit the budget and get
# axed to rest by ``_drop_unfittable_easy_days``, leaving only 2 sessions
# in 6 days. Coaching consensus is 4-5 sessions of 4-8 km pre-race.
RACE_WEEK_KM_RANGE_OVERRIDE = {
    'easy':         (5, 8),
    'recovery':     (5, 7),
    'easy_pickups': (5, 8),
}


def _km_range_for(workout_type: str, phase: str) -> tuple[int, int]:
    """Phase-aware (lo, hi) km range for a workout type.

    Race week uses lower minimums for easy / recovery / easy_pickups so a
    5 km shakeout fits the pre-race budget. All other phases use the
    canonical ``WORKOUT_KM_RANGE``.
    """
    if phase == 'Race' and workout_type in RACE_WEEK_KM_RANGE_OVERRIDE:
        return RACE_WEEK_KM_RANGE_OVERRIDE[workout_type]
    return WORKOUT_KM_RANGE.get(workout_type, (5, 8))

# Elevation density multiplier (vs. training_ratio) for non-fixed days.
ELEV_MULTIPLIER = {
    'long_run':        1.0,
    'hill_repeats':    1.2,
    'vert_session':    1.2,
    'descent_session': 1.2,  # high D+ (matches D-) for descent practice
    'intervals':       0.8,
    'uphill_intervals': 1.0,  # rolling-terrain climbing threshold; capped at 35 m/km
    'tempo':           0.7,
    'easy':            0.5,
    'easy_pickups':    0.5,
    'easy_strides':    0.3,
    'recovery':        0.3,
    'rest':            0.0,
    'race_simulation': 0.0,
    'strength':        0.0,
}

# Hard sessions need at least N days gap from another hard session.
RECOVERY_SLOTS = {
    'intervals':       2,
    'uphill_intervals': 2,
    'hill_repeats':    2,
    'vert_session':    2,
    'descent_session': 2,
    'tempo':           2,
    'long_run':        2,
}

# Phase-specific workout catalogs.
# Each phase is sized with ≤ 2 hard sessions per week (long_run aside),
# matching common ultra-trail coaching practice (Uphill Athlete, Daniels):
#   Base:  1 strength session (hill sprints) + endurance.
#   Build: strength (hill repeats, 90 s) + Z3 endurance (tempo).
#   Peak:  race specificity (vert session) + Z4 power (intervals).
# ``intensity_distribution='polarized'`` swaps the Build Z3 tempo for short Z4-Z5
# intervals (Seiler & Kjerland 2006, Scand J Med Sci Sports 16:49; Stoggl &
# Sperlich 2014, Front Physiol 5:33: polarised beats threshold-heavy for
# trained endurance athletes). Default (None / 'pyramidal') keeps the tempo.
INTENSITY_DISTRIBUTIONS = ('polarized', 'pyramidal')
PHASE_CATALOG = {
    'Base':     ['long_run', 'hill_repeats', 'easy', 'easy', 'easy', 'recovery', 'rest'],
    'Build':    ['long_run', 'hill_repeats', 'tempo', 'easy', 'easy', 'recovery', 'rest'],
    'Peak':     ['long_run', 'vert_session', 'intervals', 'easy', 'easy', 'recovery', 'rest'],
    'Recovery': ['long_run', 'easy', 'easy', 'easy', 'recovery', 'rest', 'rest'],
    'Taper':    ['long_run', 'easy_pickups', 'easy', 'rest', 'rest', 'rest', 'rest'],
    'Race':     ['race_simulation', 'easy_strides', 'recovery', 'rest', 'rest', 'rest', 'rest'],
}

# Phase-specific elevation multipliers applied on top of training_ratio.
# 1.0 = full race ratio; <1.0 = scaled-down (taper/recovery).
PHASE_ELEV_FACTOR = {
    'Base': 1.0, 'Build': 1.0, 'Peak': 1.0, 'Recovery': 0.7,
    'Taper': 0.5, 'Race': 1.0,
}

# Hill-repeat sessions look very different by phase. Sizing them from
# (training_ratio × multiplier × distance) produces 500m+ "neuromuscular hill
# sprint" weeks, which is non-physical: 6×10 sec sprints climb ~50 m total.
# Override with deterministic (km, elev) by phase.
HILL_REPEATS_PROFILE = {
    'Base':  (8.0, 80.0),    # 6x10 s sprints over an easy run
    'Build': (9.0, 280.0),   # 8x90 s climbing strength
    'Peak':  (10.0, 420.0),  # 8x2 min Z4 power
}

# Descent session: ascend to a hilltop on easy effort + 4-6 controlled
# descents of 200-400 m vert. The D+ matches the D- (you have to climb
# back up). Coaching consensus: emphasize quad eccentrics + technique.
DESCENT_SESSION_PROFILE = {
    'Base':  (9.0, 300.0),   # 3x100 m vert: first repeated-bout doses
    'Build': (11.0, 600.0),  # 4x250 m vert descents
    'Peak':  (12.0, 800.0),  # 5x300 m vert descents
}

# Race D- threshold (m) above which the engine injects descent sessions.
# Below ~1500 m of cumulative descent, generic mountain training covers
# the eccentric stimulus. Above it, structured descent practice becomes
# a specificity requirement (Vert.run, Roche).
DESCENT_TRAINING_ELEV_THRESHOLD = 1500.0

# ---------------------------------------------------------------------------
# Periodization & progression knobs (coach-tuned)
# ---------------------------------------------------------------------------

# Phase assignment
CAT1_BASE_FRACTION = 0.35
CAT2_BASE_FRACTION = 0.20
MAX_BASE_WEEKS = 4
RECOVERY_MODULATION = 3        # insert recovery every N build weeks (3:1)
TAPER_THRESHOLD_WEEKS = 6      # plans >= this get 2 taper weeks
# Block periodization (Issurin, Friel) requires accumulated fatigue for a
# Recovery week to make sense — deloading from nothing wastes a scarce
# training week. Short plans (e.g. 8-week ultra builds) routinely have a
# build_pool of 2; the previous "always insert Recovery in the last block
# slot before Peak" rule turned a 1-Build-+-Recovery-+-2-Peak structure
# into a single Build week before peaking, which is no progression at all.
# Require ≥ this many Build weeks before honouring the pre-Peak Recovery
# (coach-review #2).
MIN_BUILD_BEFORE_PRE_PEAK_RECOVERY = 2

# Long run progression
LONG_RUN_PEAK_FRACTION = 0.75
LONG_RUN_MAX_FRACTION = 0.80
LONG_RUN_TAPER1_FRACTION = 0.50
LONG_RUN_TAPER2_FRACTION = 0.35
LONG_RUN_RECOVERY_FRACTION = 0.80
# Week-1 long-run ramp-in. Coaching consensus + recent overuse-injury research
# (Damsted et al. 2018, n=5,200 — single-run >10 % of past-30-day longest
# correlates with overuse injury) wants the first programmed long run to sit
# *below* the athlete's current longest, not at it. Without this buffer, the
# linear interpolation `start + (target - start) * 1/n_prog` lands week 1 at
# 5–15 % above the athlete's longest, which is exactly the unsafe zone.
LONG_RUN_RAMP_IN_FRACTION = 0.85
# Reference multiplier used by ``services.plan_readiness`` to decide whether
# the requested race is achievable from the athlete's current baseline.
# The engine itself does NOT clip the peak long run to this value — coaching
# consensus (Higdon, Koop, CTS, Vert.run) puts the peak at 60-80 % of race
# distance and the 10 % week-over-week cap already prevents unsafe jumps.
# Safety is enforced UPSTREAM by the readiness gate refusing the plan when
# the jump exceeds ``LR_UNREALISTIC_MULTIPLIER``.
LONG_RUN_BASELINE_MULTIPLIER = 2.0

# Long-run wave / cutback pattern. Coaching consensus
# (MyProCoach, Higdon, Koop, INOV8, Relentless Forward Commotion):
# the long run should NOT plateau at peak distance for several weeks
# in a row. After two consecutive Build/Peak weeks at the same long-run
# distance (within ``LR_PLATEAU_TOLERANCE_KM``), the next Build/Peak
# week is a "stepback" week at ``LONG_RUN_STEPBACK_FRACTION`` of the
# rolling peak. This produces the up-up-cutback rhythm typical of
# real-world ultra plans: 2-3 peak-LR weeks per block, separated by
# medium-long weeks that still serve specificity but cut overall load.
LR_PLATEAU_TOLERANCE_KM = 1.0
LR_MAX_PLATEAU_LENGTH = 1          # 2nd consecutive peak week → stepback
LONG_RUN_STEPBACK_FRACTION = 0.70  # stepback long run as a fraction of peak

# Weekly volume progression
# Week 1 sits near the athlete's stated current load (coach-review #115): a 15 %
# cut on a runner already doing 65-76 km/week is a deload, not a ramp-in. Pass
# the recent 4-week average as athlete_weekly_km.
BASE_START_FRACTION = 0.95
BASE_GROWTH_PER_WEEK = 0.05
BUILD_START_FRACTION = 1.0
BUILD_GROWTH_PER_WEEK = 0.07
PEAK_VOLUME_FRACTION = 1.30
MAX_WEEKLY_INCREASE = 1.10
# Long run share of weekly volume — coach standard for ultra prep:
# weekly ≥ 2.0 × long_run (LR ≤ 50 % of the week). Numbers below this
# leave too little room for useful easy/recovery days; the engine bumps
# the weekly target up (or shrinks the long run if max_weekly_km binds).
WEEKLY_MIN_LR_MULTIPLIER = 2.0
# Build / Peak floors are tighter (2.5 = LR ≤ 40 % of weekly volume) than
# the global 2.0 because in the high-load phases the long run can easily
# absorb the entire weekly budget if left uncapped. Daniels, Friel,
# Pfitzinger all converge on "long run ≤ 30-35 % of weekly mileage";
# 40 % is the upper bound that protects against overuse without forcing
# a step-down for athletes whose ``max_weekly_km`` cap binds.
BUILD_MIN_LR_MULTIPLIER = 2.5
PEAK_MIN_LR_MULTIPLIER = 2.5

# Recovery & taper deloading
RECOVERY_VOLUME_FRACTION = 0.50
TAPER1_VOLUME_FRACTION = 0.65
TAPER2_VOLUME_FRACTION = 0.40
SINGLE_TAPER_FRACTION = 0.55
# Pre-race volume budget for race week (before the race itself).
# Coaching consensus (Mujika & Padilla 2003, Bosquet et al. 2007 meta-analysis,
# Magness, Hudson): preserve training FREQUENCY (4-5 sessions in the 6 days
# before race), cut VOLUME 40-60 %, maintain INTENSITY (strides). 30 km of
# easy + shakeout volume distributed across 4-5 short sessions delivers the
# frequency target without spiking volume. The previous 20 km collapsed to
# only 2 sessions (Wed strides + Sat strides) once the budget was sliced by
# the 8 km easy-day minimum — 4-day rest blocks pre-race induce stiffness
# without an adaptation benefit.
RACE_WEEK_EXTRA_KM = 30
RECOVERY_ELEV_FRACTION = 0.50
TAPER1_ELEV_FRACTION = 0.50
TAPER2_ELEV_FRACTION = 0.30
# Race-week elevation: light terrain rolls so easy/recovery days carry a
# few hundred m D+ (~30 m/km on rolling). 200 m budget covers 4-5 sessions
# of low-density easy without exceeding race-week recovery goals.
RACE_WEEK_EXTRA_ELEV = 200

# Elevation ramp + per-LR floor
ELEV_RAMP_FACTOR = 0.80
MIN_WEEKLY_ELEV_LR_MULT = 1.60
MIN_WEEKLY_ELEV_LR_MULT_EASY = 1.20

# Cat 1: no Z3+/intensity until this week
CAT1_INTENSITY_WEEK = 4

# Peak dress rehearsal: simulated race effort at this fraction of race
# distance. Conventional coaching: 50–65 % of race distance done at race
# effort/terrain in the last Peak week before taper.
PEAK_DRESS_REHEARSAL_FRACTION = 0.60

# Long-run week-over-week growth ceiling. More lenient than MAX_WEEKLY_INCREASE
# because the LR is the primary specificity stimulus and naturally grows faster
# than total volume. The Build/Peak ramp toward the dress rehearsal needs room
# to move; race_simulation is exempt (intentional 60 %-of-race spike).
LR_MAX_WEEKLY_INCREASE = 1.20

# Ultras (race ≥ 50K): coaching consensus (Koop, Roche/CTS, Trail Runner Mag,
# MyMottiv) is that the peak long-run / dress rehearsal should reach ~50 % of
# race distance to inoculate the runner against late-race fatigue. Below this
# threshold the plan can't fully prepare the athlete; surface as a warning,
# not an error — the user may genuinely have only X h/week and needs to know
# the trade-off, not be blocked.
ULTRA_DISTANCE_THRESHOLD_KM = 50.0
ULTRA_PEAK_LR_MIN_FRACTION = 0.50

# Vertical Kilometer / "uphill_only" races (≤ 5 km, 1000 m+ D+, ~30-90 min
# of sustained climbing). The race distance is too short to anchor a useful
# long-run target: race_distance_km × LONG_RUN_PEAK_FRACTION = 0.75 × 5 = 3.75 km
# is shorter than the athlete's existing baseline, so the engine ends up
# REGRESSING the aerobic base over the build instead of growing it.
# Coaching consensus (Vert.run "How to Train for the Hills"; Suunto "7 tips
# to accelerating your vertical speed"; Lavedrine 2024 "Running Your First
# VK"; Uphill Athlete Cat-1 framework) prescribes a weekly long mountain
# session of 1.5-2.5 h aerobic time as the central VK stimulus — the long
# run is the muscular-endurance backbone of the plan. We therefore floor
# ``target_lr`` for uphill_only races at the athlete's current longest run
# scaled by ``UPHILL_ONLY_LR_GROWTH`` (i.e. progress 25 % beyond the
# baseline over the build), gated by the standard 10 %-WoW cap upstream.
UPHILL_ONLY_LR_GROWTH = 1.25

# Race-distance regime caps for the back-to-back weekend (long_run_day - 1
# stacked with long_run_day). A 50K's biggest weekend should peak at roughly
# race distance with ~85 % of race D+; longer ultras tolerate (and need) more
# back-to-back stimulus because that's the central specificity of the
# distance. Sources: Koop "Training Essentials for Ultrarunning",
# Roche / Some Work All Play, Magness "Science of Running".
# Each entry: (max_race_km, weekend_km_fraction, weekend_elev_fraction).
# The first row whose ``max_race_km`` >= race_distance_km binds.
RACE_REGIME_WEEKEND_CAPS = (
    (40.0,            0.95, 0.80),  # marathon-ish
    (60.0,            1.00, 0.85),  # 50K
    (90.0,            1.10, 0.95),  # 50-mile
    (120.0,           1.20, 1.00),  # 100K
    (float('inf'),    1.30, 1.10),  # 100M+
)
# Floor for a hard back-to-back session after a regime trim — below this
# the workout becomes meaningless and gets degenerate. Matches the lower
# bound of WORKOUT_KM_RANGE for hard sessions.
REGIME_HARD_FLOOR_KM = 8.0
REGIME_HARD_FLOOR_ELEV = 200.0

# ---------------------------------------------------------------------------
# Required preferences (gate)
# ---------------------------------------------------------------------------

REQUIRED_PREFS_FIELDS = ('max_weekly_km', 'terrain_profile')


class MissingPreferencesError(Exception):
    """Raised when required user prefs are absent.

    The orchestrator catches this and asks the agent/UI to surface the
    onboarding wizard before retrying generation.
    """

    def __init__(self, missing_fields: list[str]):
        self.missing_fields = list(missing_fields)
        super().__init__(
            f"Missing required training preferences: {', '.join(self.missing_fields)}"
        )


# ---------------------------------------------------------------------------
# LLM-tunable parameters (clamped to bounds for safety)
# ---------------------------------------------------------------------------

TUNABLE_DEFAULTS = {
    'long_run_peak_fraction': LONG_RUN_PEAK_FRACTION,
    'long_run_taper1_fraction': LONG_RUN_TAPER1_FRACTION,
    'long_run_taper2_fraction': LONG_RUN_TAPER2_FRACTION,
    'base_growth_per_week': BASE_GROWTH_PER_WEEK,
    'build_growth_per_week': BUILD_GROWTH_PER_WEEK,
    'peak_volume_fraction': PEAK_VOLUME_FRACTION,
    'recovery_volume_fraction': RECOVERY_VOLUME_FRACTION,
    'taper1_volume_fraction': TAPER1_VOLUME_FRACTION,
    'taper2_volume_fraction': TAPER2_VOLUME_FRACTION,
    'elev_ramp_factor': ELEV_RAMP_FACTOR,
    'recovery_elev_fraction': RECOVERY_ELEV_FRACTION,
    'taper1_elev_fraction': TAPER1_ELEV_FRACTION,
    'taper2_elev_fraction': TAPER2_ELEV_FRACTION,
}

TUNABLE_BOUNDS = {
    'long_run_peak_fraction':    (0.50, 0.85),
    'long_run_taper1_fraction':  (0.30, 0.60),
    'long_run_taper2_fraction':  (0.20, 0.45),
    'base_growth_per_week':      (0.03, 0.10),
    'build_growth_per_week':     (0.04, 0.12),
    'peak_volume_fraction':      (1.10, 1.60),
    'recovery_volume_fraction':  (0.35, 0.60),
    'taper1_volume_fraction':    (0.45, 0.75),
    'taper2_volume_fraction':    (0.25, 0.50),
    'elev_ramp_factor':          (0.50, 1.00),
    'recovery_elev_fraction':    (0.30, 0.60),
    'taper1_elev_fraction':      (0.30, 0.60),
    'taper2_elev_fraction':      (0.15, 0.45),
}


def _resolve_tunables(overrides: dict | None) -> dict:
    """Merge user overrides with defaults, clamping to safety bounds."""
    params = dict(TUNABLE_DEFAULTS)
    if not overrides:
        return params
    for key, value in overrides.items():
        if key not in TUNABLE_DEFAULTS:
            continue
        lo, hi = TUNABLE_BOUNDS.get(key, (value, value))
        params[key] = max(lo, min(hi, float(value)))
    return params


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WeekTarget:
    """Computed volume targets for a single week."""
    week_number: int
    phase: str
    weekly_km: float
    weekly_elev: float
    long_run_km: float
    long_run_elev: float
    peak_weekly_km: float = 0.0


@dataclass
class DayWorkout:
    """A single day's workout prescription."""
    day: str
    date: str
    workout_type: str
    title: str
    distance_km: float
    elevation_m: float
    intensity: str
    notes: str
    route_id: Optional[int] = None
    route_match_quality: str = 'pending'
    suggested_alternatives: list = field(default_factory=list)


# =========================================================================
# Layer 1: Phase Assignment
# =========================================================================

def assign_phases(total_weeks: int, athlete_category: str) -> list[str]:
    """Assign mesocycle phases to each week.

    Builds the plan back-to-front from race day:
      1. Race week (always last).
      2. Taper (1 week if total < 6, else 2).
      3. Peak block (up to 2 weeks).
      4. Recovery week immediately before Peak when there is room.
      5. Build block with 3:1 modulation (recovery every ``RECOVERY_MODULATION``).
      6. Base block at the start, sized by category.

    A small final pad/trim ensures ``len(phases) == total_weeks``.
    """
    if total_weeks < 2:
        return ['Race']

    taper_weeks = 1 if total_weeks < TAPER_THRESHOLD_WEEKS else 2
    available = total_weeks - 1 - taper_weeks  # for Base/Build/Peak/Recovery

    if available <= 0:
        return ['Taper'] * taper_weeks + ['Race']

    base_fraction = (CAT1_BASE_FRACTION if athlete_category == 'cat_1'
                     else CAT2_BASE_FRACTION)
    base_weeks = min(MAX_BASE_WEEKS, available, max(1, round(available * base_fraction)))
    remaining = available - base_weeks

    # Peak: at most 2 weeks, requires room for at least 1 build to feed it.
    peak_weeks = min(2, max(0, remaining - 2))
    build_pool = remaining - peak_weeks  # build + (recovery insertions)

    # Build the block with strict 3:1 modulation (RECOVERY_MODULATION).
    # The last slot is normally a Recovery before Peak so the athlete
    # enters peak fresh; in tight build_pools (e.g. 12-week plans) this
    # can land adjacent to a modulation Recovery — a 2-week deload is
    # preferable to a 4th consecutive Build.
    #
    # Exception: when fewer than MIN_BUILD_BEFORE_PRE_PEAK_RECOVERY Build
    # weeks have accumulated, skip the pre-Peak Recovery — there is no
    # fatigue to recover from and the slot is more useful as another Build
    # week. Without this guard, an 8-week ultra plan with build_pool=2 ends
    # up as Build-Recovery-Peak-Peak (only 1 Build week before Peak), which
    # delivers essentially no progression stimulus before peaking
    # (coach-review #2 — Issurin block periodization, Friel).
    block: list[str] = []
    consecutive = 0
    for i in range(build_pool):
        is_last_block_slot = (i == build_pool - 1)
        builds_so_far = sum(1 for x in block if x == 'Build')
        wants_pre_peak_recovery = (
            peak_weeks > 0 and is_last_block_slot
            and builds_so_far >= MIN_BUILD_BEFORE_PRE_PEAK_RECOVERY
        )
        if wants_pre_peak_recovery:
            block.append('Recovery')
        elif consecutive >= RECOVERY_MODULATION:
            block.append('Recovery')
            consecutive = 0
        else:
            block.append('Build')
            consecutive += 1

    phases = ['Base'] * base_weeks + block + ['Peak'] * peak_weeks \
             + ['Taper'] * taper_weeks + ['Race']

    # Pad / trim — the constructive build can over- or under-shoot by 1.
    if len(phases) > total_weeks:
        phases = _trim_phases(phases, total_weeks)
    elif len(phases) < total_weeks:
        deficit = total_weeks - len(phases)
        phases = ['Base'] * deficit + phases

    return phases


def _trim_phases(phases: list[str], target_len: int) -> list[str]:
    """Remove weeks in priority order: extra Base, then Build, then Recovery, then Peak."""
    drop_order = ('Base', 'Build', 'Recovery', 'Peak')
    minimums = {'Base': 1, 'Build': 0, 'Recovery': 0, 'Peak': 1, 'Taper': 1, 'Race': 1}
    out = list(phases)
    for kind in drop_order:
        while len(out) > target_len and out.count(kind) > minimums.get(kind, 0):
            # Remove the earliest occurrence to keep the closest-to-race shape.
            out.pop(out.index(kind))
    return out


# =========================================================================
# Layer 2: Weekly Targets
# =========================================================================

def _phase_positions(phases: list[str]) -> dict[str, dict[int, int]]:
    """For each phase, map week_idx -> position-within-phase."""
    out: dict[str, dict[int, int]] = {p: {} for p in VALID_PHASES}
    counters: dict[str, int] = {p: 0 for p in VALID_PHASES}
    for i, p in enumerate(phases):
        out[p][i] = counters[p]
        counters[p] += 1
    return out


def _progression_position(phases: list[str]) -> tuple[dict[int, int], int]:
    prog = [i for i, p in enumerate(phases) if p in ('Base', 'Build', 'Peak')]
    return {idx: pos for pos, idx in enumerate(prog)}, len(prog)


def _long_run_for(
    phase: str, week_idx: int,
    *,
    start_lr: float, target_lr: float,
    progression_pos: dict[int, int], n_prog: int,
    phase_pos: dict[str, dict[int, int]], n_taper: int,
    athlete_longest_run_km: float, race_distance_km: float,
    peak_lr_so_far: float,
    T: dict,
    race_type: str = 'loop',
) -> float:
    """Long-run distance for a single week.

    ``peak_lr_so_far`` is the largest long-run actually programmed up to
    (but not including) this week, after every Base/Build/Peak cap was
    applied. Taper deloads from THAT, not from the unclamped target.
    Without this, an hours-budget that clips the Build/Peak long run
    leaves the taper formula sized off ``target_lr`` (race × 0.75) — so
    the taper-1 long run can come out larger than the peak long run the
    athlete actually trained, which is the opposite of a deload.
    """
    if phase in ('Base', 'Build', 'Peak') and n_prog > 0:
        # Position-aware ramp: the FIRST progression week sits at ``start_lr``
        # (the documented ramp-in floor — LONG_RUN_RAMP_IN_FRACTION * athlete
        # longest, see Damsted et al. 2018 cited in LONG_RUN_RAMP_IN_FRACTION).
        # Without ``frac=0`` at pos=0 the linear interpolation immediately
        # overshoots the safety floor (e.g. for n_prog=4 the first week lands
        # at start_lr + 25% × (target − start), which can equal or exceed the
        # athlete's recent longest run — exactly the >10 % single-run jump
        # the cited research flags as 64 % higher overuse-injury risk
        # (coach-review #1).
        denom = max(1, n_prog - 1)
        frac = progression_pos.get(week_idx, 0) / denom
        lr = start_lr + (target_lr - start_lr) * frac
        # The trailing ``race_distance_km × LONG_RUN_MAX_FRACTION`` clamp is a
        # safety net for road / ultra plans (LR ≤ 80 % of race distance). For
        # VK / uphill_only races it would re-clamp the LR back to 0.8 × 5 = 4
        # km and silently undo the UPHILL_ONLY_LR_GROWTH override — defeating
        # the entire long-aerobic-mountain stimulus. ``target_lr`` is already
        # the binding upper bound for VK (set in ``compute_weekly_targets``).
        if race_type == 'uphill_only':
            return min(lr, target_lr)
        return min(lr, race_distance_km * LONG_RUN_MAX_FRACTION)
    if phase == 'Recovery':
        return min(start_lr * LONG_RUN_RECOVERY_FRACTION, athlete_longest_run_km)
    if phase == 'Taper':
        pos = phase_pos['Taper'].get(week_idx, 0)
        f = (T['long_run_taper1_fraction'] if (n_taper == 1 or pos == 0)
             else T['long_run_taper2_fraction'])
        # Deload from achieved peak when available; fall back to target_lr
        # only when no Build/Peak week has been programmed yet (very short
        # plans where Taper directly follows Base).
        base_lr = min(target_lr, peak_lr_so_far) if peak_lr_so_far > 0 else target_lr
        lr = base_lr * f
        # Defensive Taper LR floor (coach-review #45). Bosquet et al. 2007
        # taper meta-analysis: Taper-2 sits at 30-40 % of peak typically,
        # never below 20 % (= TUNABLE_BOUNDS lower for long_run_taper2_fraction).
        # Without an explicit floor, a pathological combination (target_lr
        # collapse + tunable on lower bound + WoW propagation chain) can
        # zero out the long run (issue #45 reported 1.4 km on a VK plan
        # whose peak was 14 km). Anchor the floor at 25 % of the achieved
        # peak so the primary specificity stimulus survives the deload.
        if peak_lr_so_far > 0:
            lr = max(lr, peak_lr_so_far * 0.25)
        return lr
    if phase == 'Race':
        return 0.0
    return start_lr


def _weekly_km_for(
    phase: str, week_idx: int,
    *,
    athlete_weekly_km: float, race_distance_km: float,
    long_run_km: float, peak_km_so_far: float, prev_build_km: float,
    phase_pos: dict[str, dict[int, int]], n_taper: int,
    T: dict,
) -> float:
    """Raw weekly km target before caps and floors."""
    if phase == 'Base':
        pos = phase_pos['Base'].get(week_idx, 0)
        km = athlete_weekly_km * (BASE_START_FRACTION + T['base_growth_per_week'] * pos)
        return max(km, long_run_km * WEEKLY_MIN_LR_MULTIPLIER)
    if phase == 'Build':
        pos = phase_pos['Build'].get(week_idx, 0)
        km = athlete_weekly_km * (BUILD_START_FRACTION + T['build_growth_per_week'] * pos)
        return max(km, long_run_km * BUILD_MIN_LR_MULTIPLIER)
    if phase == 'Peak':
        km = athlete_weekly_km * T['peak_volume_fraction']
        return max(km, long_run_km * PEAK_MIN_LR_MULTIPLIER)
    if phase == 'Recovery':
        return prev_build_km * T['recovery_volume_fraction']
    if phase == 'Taper':
        pos = phase_pos['Taper'].get(week_idx, 0)
        f = (T['taper1_volume_fraction'] if (n_taper == 1 or pos == 0)
             else T['taper2_volume_fraction'])
        return peak_km_so_far * f
    if phase == 'Race':
        return RACE_WEEK_EXTRA_KM + race_distance_km
    return athlete_weekly_km


def _weekly_elev_for(
    phase: str, week_idx: int,
    *,
    athlete_weekly_elev: float, race_elevation_m: float,
    progression_pos: dict[int, int], n_prog: int,
    phase_pos: dict[str, dict[int, int]], n_taper: int,
    prev_build_km: float, training_ratio: float,
    T: dict,
) -> float:
    """Raw weekly D+ target before per-day capping."""
    if phase in ('Base', 'Build') and n_prog > 0 and week_idx in progression_pos:
        frac = (progression_pos[week_idx] + 1) / n_prog
        return (athlete_weekly_elev
                + (race_elevation_m - athlete_weekly_elev) * frac * T['elev_ramp_factor'])
    if phase == 'Peak':
        return race_elevation_m
    if phase == 'Recovery':
        return prev_build_km * training_ratio * T['recovery_elev_fraction']
    if phase == 'Taper':
        pos = phase_pos['Taper'].get(week_idx, 0)
        f = (T['taper1_elev_fraction'] if (n_taper == 1 or pos == 0)
             else T['taper2_elev_fraction'])
        return race_elevation_m * f
    if phase == 'Race':
        return race_elevation_m + RACE_WEEK_EXTRA_ELEV
    return athlete_weekly_elev


def _estimate_week_hours(
    weekly_km: float, weekly_elev: float,
    long_run_km: float, long_run_elev: float,
) -> float | None:
    """Rough wall-clock estimate for a target week.

    Splits the week into the long run (priced at ``long_run`` effort) and
    the rest (priced at ``easy`` effort). Mirrors what the validator does
    per-day in ``_check_week_hours`` — close enough at the planning stage
    where days haven't been distributed yet. Returns ``None`` if the
    physics module isn't importable (test environments without it).
    """
    _, predict = _import_time_budget()
    if predict is None:
        return None
    lr_h = predict(long_run_km, long_run_elev, learned_params=None, effort='long_run')
    rest_km = max(0.0, weekly_km - long_run_km)
    rest_elev = max(0.0, weekly_elev - long_run_elev)
    rest_h = predict(rest_km, rest_elev, learned_params=None, effort='easy')
    return lr_h + rest_h


_MID_WEEK_FLOOR_FRACTION = 0.55


def _enforce_hours_budget(
    weekly_km: float, weekly_elev: float,
    long_run_km: float, long_run_elev: float,
    available_hours: float,
    phase: str, training_ratio: float,
) -> tuple[float, float, float, float]:
    """Scale weekly + long-run targets down so they fit ``available_hours``.

    Strategy: when the estimate exceeds the budget, prioritise the long
    run (primary specificity stimulus). Cut mid-week volume first down to
    ``_MID_WEEK_FLOOR_FRACTION`` of its original hours; only when the
    mid-week is at its floor does the LR start to shrink. This keeps
    Build/Peak progression alive under tight hours budgets — a flat 12 h
    plan no longer collapses every week onto the same 32 km LR ceiling.

    Mid-week floor (55 %) is empirically chosen: deeper cuts force easy
    days below the coaching minimum (≥ 6 km easy, see
    ``_drop_unfittable_easy_days``) and the engine ends up dropping
    sessions to rest. Above ~55 % the easy/recovery scaffolding around
    the long run survives.

    Skipped on Recovery / Taper / Race phases — those are intentional
    deloads and the engine sizes them well below normal budgets.
    """
    if available_hours <= 0 or phase in ('Recovery', 'Taper', 'Race'):
        return weekly_km, weekly_elev, long_run_km, long_run_elev
    est = _estimate_week_hours(weekly_km, weekly_elev, long_run_km, long_run_elev)
    if est is None or est <= available_hours * 1.10:
        return weekly_km, weekly_elev, long_run_km, long_run_elev

    _, predict = _import_time_budget()
    if predict is None:
        # Fallback: legacy proportional scaling (predict gone, can't
        # compute LR vs mid-week split).
        scale = available_hours / est
        weekly_km *= scale
        weekly_elev *= scale
        lr_scale = scale ** 0.5
        long_run_km *= lr_scale
        long_run_elev *= lr_scale
    else:
        # LR-priority scaling: cut mid-week first, only touch the LR
        # once mid-week has hit its floor.
        lr_h = predict(long_run_km, long_run_elev, learned_params=None, effort='long_run')
        mid_h = max(0.0, est - lr_h)
        need_to_cut = est - available_hours
        mid_max_cut = mid_h * (1.0 - _MID_WEEK_FLOOR_FRACTION)

        if need_to_cut <= mid_max_cut and mid_h > 0:
            # Entire shortfall absorbed by mid-week.
            mid_scale = (mid_h - need_to_cut) / mid_h
            lr_scale = 1.0
        elif mid_h > 0:
            # Mid-week to floor; remainder pulled from the long run.
            mid_scale = _MID_WEEK_FLOOR_FRACTION
            cut_from_lr = need_to_cut - mid_max_cut
            lr_scale = max(0.40, (lr_h - cut_from_lr) / lr_h) if lr_h > 0 else 1.0
        else:
            # Degenerate case: no mid-week (LR is the whole week).
            mid_scale = 1.0
            lr_scale = available_hours / est

        mid_km = max(0.0, weekly_km - long_run_km)
        mid_elev = max(0.0, weekly_elev - long_run_elev)
        long_run_km *= lr_scale
        long_run_elev *= lr_scale
        weekly_km = long_run_km + mid_km * mid_scale
        weekly_elev = long_run_elev + mid_elev * mid_scale

    # We intentionally do NOT re-enforce the WEEKLY_MIN_LR_MULTIPLIER floor
    # here. When the budget binds, the LR-priority scaling above can push
    # the LR / weekly ratio above the 2.0 coaching ideal — that's the
    # whole point: keep specificity stimulus alive at the cost of mid-week
    # easy volume. A user with a tight hours budget genuinely cannot do
    # both, and shrinking the LR back down recreates the original plateau.
    # The peak_lr_below_ultra_target feasibility warning surfaces when
    # this trade-off still leaves the LR under-target.
    return weekly_km, weekly_elev, long_run_km, long_run_elev


def _floor_mult_for(
    phase: str, week_idx: int, phase_pos: dict[str, dict[int, int]],
) -> float:
    """LR-to-weekly floor multiplier with Base→Build transition smoothing.

    Raw rule: Base = 2.0, Build/Peak = 2.5 (LR ≤ 40 % of weekly volume in
    the high-load phases, per Daniels / Friel / Pfitzinger / Koop). The
    discontinuous 2.0 → 2.5 jump forces a ~25 % weekly_km increase at the
    phase boundary that violates the 10 %-week cap (issue #37). The last
    two Base weeks ramp 2.0 → 2.17 → 2.33 so the transition is gradual:
    each floor step is ~+8 %, leaving room for the natural ~10 % LR growth
    without the joint effect blowing past the 10 %-week ceiling.
    """
    if phase == 'Base':
        base_pos = phase_pos['Base'].get(week_idx)
        n_base = len(phase_pos['Base'])
        if base_pos is None:
            return WEEKLY_MIN_LR_MULTIPLIER
        pos_from_end = (n_base - 1) - base_pos
        delta = BUILD_MIN_LR_MULTIPLIER - WEEKLY_MIN_LR_MULTIPLIER
        if pos_from_end == 0 and n_base >= 1:
            return WEEKLY_MIN_LR_MULTIPLIER + delta * (2.0 / 3.0)
        if pos_from_end == 1 and n_base >= 2:
            return WEEKLY_MIN_LR_MULTIPLIER + delta * (1.0 / 3.0)
        return WEEKLY_MIN_LR_MULTIPLIER
    if phase in ('Build', 'Peak'):
        return BUILD_MIN_LR_MULTIPLIER
    return WEEKLY_MIN_LR_MULTIPLIER


def compute_weekly_targets(
    phases: list[str],
    athlete_weekly_km: float,
    athlete_weekly_elev: float,
    athlete_longest_run_km: float,
    race_distance_km: float,
    race_elevation_m: float,
    training_ratio: float | None = None,
    tunables: dict | None = None,
    *,
    race_type: str = 'loop',
    max_weekly_km: float | None = None,
    max_long_run_km: float | None = None,
    max_long_run_hours: float | None = None,
    athlete_flat_pace_min_km: float | None = None,
    available_hours_per_week: float | None = None,
    long_long_run_hours: float | None = None,
    long_long_run_every_weeks: int | None = None,
) -> list[WeekTarget]:
    """Compute per-week (km, D+, long_run_km, long_run_elev) targets.

    Each phase contributes via the small ``_long_run_for`` / ``_weekly_km_for``
    / ``_weekly_elev_for`` helpers. After raw values are computed we apply,
    in order: 10 %-week-over-week cap, user volume / long-run caps, and
    per-LR weekly floor.
    """
    if training_ratio is None:
        training_ratio = race_elevation_m / race_distance_km if race_distance_km > 0 else 0
    T = tunables or TUNABLE_DEFAULTS

    target_lr = min(race_distance_km * T['long_run_peak_fraction'],
                    race_distance_km * LONG_RUN_MAX_FRACTION)
    # VK / uphill_only floor: a 5 km race × 0.75 = 3.75 km LR target is shorter
    # than the athlete's existing longest run, so the engine would deliberately
    # detrain the aerobic base over the build. Anchor the target to the athlete
    # baseline + UPHILL_ONLY_LR_GROWTH (see constant docstring for citations).
    if race_type == 'uphill_only' and athlete_longest_run_km > 0:
        target_lr = max(target_lr, athlete_longest_run_km * UPHILL_ONLY_LR_GROWTH)
    # Ramp-in buffer: week-1 LR sits below the athlete's recent longest so the
    # first programmed week never exceeds what the body has already adapted to.
    # See LONG_RUN_RAMP_IN_FRACTION docstring for the safety rationale.
    start_lr = min(athlete_longest_run_km * LONG_RUN_RAMP_IN_FRACTION, target_lr)

    progression_pos, n_prog = _progression_position(phases)
    phase_pos = _phase_positions(phases)
    n_taper = phases.count('Taper')

    # "Long-long" run (e.g. 4 h once a month, 3 h otherwise): every Nth Build/Peak
    # week (dress rehearsal excluded) swaps max_long_run_hours for
    # long_long_run_hours and skips the LR growth cap (a deliberate pulse).
    long_long_weeks: set[int] = set()
    if long_long_run_hours and long_long_run_every_weeks and long_long_run_every_weeks > 0:
        last_peak = max((i for i, p in enumerate(phases) if p == 'Peak'), default=-1)
        elig = [i for i, p in enumerate(phases)
                if p in ('Build', 'Peak') and i != last_peak]
        long_long_weeks = {w for k, w in enumerate(elig)
                           if (k + 1) % long_long_run_every_weeks == 0}

    targets: list[WeekTarget] = []
    peak_km = athlete_weekly_km
    # ``peak_lr`` tracks the largest long-run actually programmed (after
    # all caps: max_long_run_km, max_long_run_hours, hours-budget). It's
    # the deload reference point for Taper weeks — see ``_long_run_for``.
    peak_lr = 0.0
    prev_build_km = athlete_weekly_km

    for week_idx, phase in enumerate(phases):
        long_run_km = _long_run_for(
            phase, week_idx,
            start_lr=start_lr, target_lr=target_lr,
            progression_pos=progression_pos, n_prog=n_prog,
            phase_pos=phase_pos, n_taper=n_taper,
            athlete_longest_run_km=athlete_longest_run_km,
            race_distance_km=race_distance_km,
            peak_lr_so_far=peak_lr, T=T,
            race_type=race_type,
        )
        weekly_km = _weekly_km_for(
            phase, week_idx,
            athlete_weekly_km=athlete_weekly_km, race_distance_km=race_distance_km,
            long_run_km=long_run_km, peak_km_so_far=peak_km,
            prev_build_km=prev_build_km, phase_pos=phase_pos,
            n_taper=n_taper, T=T,
        )

        # 10 %-week cap on increase from the previous progression week.
        # Same cap on long_run_km but more lenient (LR_MAX_WEEKLY_INCREASE,
        # ~20 %): the LR is the primary specificity stimulus and tracks
        # ahead of total volume. The race_simulation dress rehearsal is
        # exempt — it's sized independently in distribute_week
        # (PEAK_DRESS_REHEARSAL_FRACTION × race_distance_km), not via
        # long_run_km, so this cap can't block it. Acolyte safety check
        # against unintended +50 % LR jumps in pathological inputs.
        if phase in ('Base', 'Build', 'Peak'):
            for prev in reversed(targets):
                if prev.phase not in ('Recovery', 'Taper', 'Race'):
                    weekly_km = min(weekly_km, prev.weekly_km * MAX_WEEKLY_INCREASE)
                    if week_idx not in long_long_weeks:
                        long_run_km = min(
                            long_run_km, prev.long_run_km * LR_MAX_WEEKLY_INCREASE,
                        )
                    break

        if phase in ('Build', 'Peak'):
            peak_km = max(peak_km, weekly_km)
            prev_build_km = weekly_km

        weekly_elev = _weekly_elev_for(
            phase, week_idx,
            athlete_weekly_elev=athlete_weekly_elev, race_elevation_m=race_elevation_m,
            progression_pos=progression_pos, n_prog=n_prog,
            phase_pos=phase_pos, n_taper=n_taper,
            prev_build_km=prev_build_km, training_ratio=training_ratio, T=T,
        )

        # Long-run elevation density: ramp from athlete baseline to race
        # ratio across Base/Build, hit race ratio in Peak. Vert.run / Koop
        # / Roche all converge on "the LR matches or slightly exceeds race
        # density by Peak — not from week 1". A linear ramp from
        # ``athlete_density`` (athlete_weekly_elev / athlete_weekly_km) to
        # ``training_ratio`` over the progression keeps W1 inside the
        # athlete's adapted range while still arriving at race-specific
        # density by Peak. When the athlete already trains denser than the
        # race needs, the start anchor caps at training_ratio so the LR
        # doesn't exceed race density gratuitously (issue #34). Computed
        # before the caps so the hours cap sees the real LR density (#115).
        athlete_density = (athlete_weekly_elev / max(athlete_weekly_km, 1.0))
        ramp_start = min(athlete_density, training_ratio)
        if (phase in ('Base', 'Build') and n_prog > 0
                and week_idx in progression_pos):
            frac = (progression_pos[week_idx] + 1) / n_prog
            lr_density = ramp_start + (training_ratio - ramp_start) * frac
        elif phase == 'Recovery':
            # Easy weekend on the deload — sit at the ramp start.
            lr_density = ramp_start
        else:
            # Peak / Taper: full race-specific density, scaled by the
            # phase factor below.
            lr_density = training_ratio

        # User capacity caps (applied AFTER natural progression).
        if max_long_run_km is not None and long_run_km > max_long_run_km:
            long_run_km = max_long_run_km
        # Long-run hours cap, sized with the same time model the validator uses
        # (predict_time_for_distance, via its inverse) so a "3 h" cap cannot
        # yield a long run that the validation later prices at 5.5 h
        # (coach-review #115). Long-long weeks use their own cap.
        lr_hours_cap = (long_long_run_hours if week_idx in long_long_weeks
                        else max_long_run_hours)
        if lr_hours_cap is not None and phase != 'Race':
            _, predict = _import_time_budget()
            density = lr_density * PHASE_ELEV_FACTOR.get(phase, 1.0)
            if predict is not None:
                from services.physics_model.time_budget import predict_distance_for_time
                km_from_hours = predict_distance_for_time(
                    float(lr_hours_cap), density, learned_params=None, effort='long_run',
                )[0]
            elif athlete_flat_pace_min_km:
                # Naismith-style fallback: pace x (1 + d / 100).
                effective_pace = athlete_flat_pace_min_km * (1.0 + density / 100.0)
                km_from_hours = (lr_hours_cap * 60.0) / max(effective_pace, 1.0)
            else:
                km_from_hours = long_run_km
            if long_run_km > km_from_hours:
                long_run_km = km_from_hours
        # Race week is exempt: weekly_km here = race_distance + RACE_WEEK_EXTRA_KM
        # (the race itself is event-day load, not training load). Clamping race
        # week to max_weekly_km zeros out the pre-race budget when the race
        # distance equals the cap (e.g. 100 km race with 100 km cap), leaving
        # only the pre-pinned shakeouts and forcing 4-5 rest days in the
        # 6-day pre-race window — too aggressive a deload (Mujika & Padilla
        # 2003, Bosquet et al. 2007: maintain frequency, cut volume only).
        if (max_weekly_km is not None and weekly_km > max_weekly_km
                and phase != 'Race'):
            weekly_km = max_weekly_km

        # Re-enforce: weekly_km >= floor * long_run_km.
        # Skipped in Taper / Race: the long_run is intentionally a larger
        # fraction of a smaller week; pushing weekly_km up to 2× LR would
        # undo the deload — that's how Taper-1 was ending up larger than
        # the preceding Peak week. Recovery keeps the floor so the easy
        # mid-week volume around the recovery long-run isn't all rest.
        # Phase-correct floor: Build / Peak need the tighter LR ≤ 40 % of
        # weekly volume (mult=2.5) to avoid the LR cannibalising the entire
        # week — Daniels / Friel / Pfitzinger / Koop converge on this bound.
        # Without phase-awareness, max_weekly_km truncation lets a Peak LR
        # sit at 50–70 % of weekly volume (e.g. 60 km LR in an 86 km cap)
        # which is overuse-injury territory.
        #
        # Base→Build smoothing: the raw 2.0 → 2.5 jump at the phase boundary
        # forces a ~25 % weekly_km increase that blows past the 10 %-week
        # cap. The last Base week ramps to the midpoint (2.25) so the
        # transition is monotonic — Build then steps to 2.5 with only a
        # ~10 % weekly bump. Closer to coaching practice (Daniels, Friel)
        # than a discontinuous floor change at the phase boundary.
        floor_mult = _floor_mult_for(phase, week_idx, phase_pos)
        if (phase not in ('Taper', 'Race')
                and weekly_km < floor_mult * long_run_km):
            need = floor_mult * long_run_km
            if max_weekly_km is not None and need > max_weekly_km:
                long_run_km = max_weekly_km / floor_mult
                weekly_km = max_weekly_km
            else:
                weekly_km = need
            # Hard 10 %-week cap: when the floor enforcement just pushed
            # weekly_km past prev * MAX_WEEKLY_INCREASE, shrink the long
            # run instead (option B from issue #37). Monotonicity guard:
            # never shrink LR below the previous progression week's LR —
            # the natural progression must always grow or hold flat.
            # Skipping Recovery / Taper / Race for ``prev`` matches the
            # existing 10 %-week cap above (deload weeks aren't a
            # progression baseline). When the guard binds, weekly_km can
            # still nudge above the cap (LR can't shrink) — that's the
            # intended trade-off: protect LR specificity over volume.
            if phase in ('Base', 'Build', 'Peak') and floor_mult > 0:
                for prev in reversed(targets):
                    if prev.phase not in ('Recovery', 'Taper', 'Race'):
                        cap = prev.weekly_km * MAX_WEEKLY_INCREASE
                        if weekly_km > cap:
                            new_lr = min(long_run_km, cap / floor_mult)
                            new_lr = max(new_lr, prev.long_run_km)
                            weekly_km = max(cap, new_lr * floor_mult)
                            long_run_km = new_lr
                        break

        # Belt-and-braces: a Taper week must never exceed the peak weekly
        # volume the athlete actually trained. Mujika & Padilla's taper
        # review (and every ultra coach: Koop, Roche, Magness, CTS) is
        # unanimous — taper REDUCES from peak.
        if phase == 'Taper':
            weekly_km = min(weekly_km, peak_km)

        if phase == 'Race':
            long_run_elev = 0.0
        else:
            long_run_elev = long_run_km * lr_density * PHASE_ELEV_FACTOR.get(phase, 1.0)

        # Weekly D+ floor relative to the long run (so weekday rolling
        # carries real climb, not just the long run).
        floor_mult = (MIN_WEEKLY_ELEV_LR_MULT if phase not in ('Recovery', 'Taper', 'Race')
                      else MIN_WEEKLY_ELEV_LR_MULT_EASY)
        weekly_elev = max(weekly_elev, long_run_elev * floor_mult)

        # Hours budget enforcement (Minetti-based). Without this, a 10 h/week
        # athlete on a mountainous plan can land at 13–15 h/week of build
        # weeks because km/elev are computed independently of metabolic cost.
        # Validator surfaces this as ``weekly_hours_above_cap`` post-hoc; we
        # enforce it during generation so the warning never fires for a
        # plan that respected the budget.
        if available_hours_per_week is not None:
            weekly_km, weekly_elev, long_run_km, long_run_elev = _enforce_hours_budget(
                weekly_km, weekly_elev, long_run_km, long_run_elev,
                available_hours=float(available_hours_per_week),
                phase=phase, training_ratio=training_ratio,
            )

        # Peak monotonicity: under a tight hours budget, ``_enforce_hours_budget``
        # can shrink a Peak LR below the previously-achieved peak (e.g. an
        # 8-week 50K plan with 10 h/wk produced W4 Peak LR = 28.6 km < W2
        # Build LR = 30.6 km — periodization in reverse). The dress rehearsal
        # is sized separately in ``distribute_week`` and is exempt; for normal
        # Peak weeks we restore the LR floor at the prior peak. The validator
        # will then surface the hours overage as ``weekly_hours_above_cap``,
        # which is the right trade-off to communicate (Mujika & Padilla,
        # Magness): coach-correct is to keep the central specificity stimulus
        # alive and warn the athlete the week runs long, not to silently break
        # Build→Peak progression (coach-review #4).
        if phase == 'Peak' and peak_lr > 0 and long_run_km < peak_lr:
            long_run_km = peak_lr
            long_run_elev = max(
                long_run_elev,
                long_run_km * training_ratio * PHASE_ELEV_FACTOR.get('Peak', 1.0),
            )
            weekly_elev = max(weekly_elev,
                              long_run_elev * MIN_WEEKLY_ELEV_LR_MULT)

        # Track the achieved peak LR (after every cap) so subsequent
        # Taper weeks can deload from it. Recovery is excluded — its LR
        # is already a step-back and shouldn't anchor the taper.
        if phase in ('Base', 'Build', 'Peak') and week_idx not in long_long_weeks:
            peak_lr = max(peak_lr, long_run_km)

        targets.append(WeekTarget(
            week_number=week_idx + 1, phase=phase,
            weekly_km=round(weekly_km, 1), weekly_elev=round(weekly_elev, 0),
            long_run_km=round(long_run_km, 1),
            long_run_elev=round(long_run_elev, 0),
            peak_weekly_km=peak_km,
        ))

    _apply_long_run_wave(targets, training_ratio)
    return targets


def _apply_long_run_wave(targets: list[WeekTarget], training_ratio: float) -> None:
    """Break long-run plateaus by inserting stepback weeks in-place.

    A "plateau" is a run of Build/Peak weeks where the long-run distance
    stays within ``LR_PLATEAU_TOLERANCE_KM`` of the previous Build/Peak
    long run. After ``LR_MAX_PLATEAU_LENGTH`` consecutive plateau weeks,
    the next Build/Peak week is rewritten to ``LONG_RUN_STEPBACK_FRACTION``
    of the plateau distance. The plateau counter resets on a stepback
    or on a Recovery / Taper / Race week, so each Build block can have
    at most ``LR_MAX_PLATEAU_LENGTH + 1`` weeks at peak before forcing a
    cutback. Weekly volume is left untouched — only the long run and
    its elevation move.
    """
    plateau_len = 0
    prev_peak: float | None = None
    for i, t in enumerate(targets):
        if t.phase not in ('Build', 'Peak'):
            plateau_len = 0
            prev_peak = None
            continue

        # Don't down-shift the dress rehearsal: race_simulation in the
        # last Peak week is sized in distribute_week, but we'd rather
        # this function not touch the final peak target either.
        is_at_plateau = (
            prev_peak is not None
            and abs(t.long_run_km - prev_peak) <= LR_PLATEAU_TOLERANCE_KM
        )
        # A Recovery / Taper week right after already is the cutback: stepping
        # back the week before it double-deloads (week 7 -> 8 dip, #115).
        next_is_deload = (i + 1 < len(targets)
                          and targets[i + 1].phase in ('Recovery', 'Taper', 'Race'))
        if is_at_plateau:
            plateau_len += 1
            if plateau_len > LR_MAX_PLATEAU_LENGTH and not next_is_deload:
                stepback_km = round(prev_peak * LONG_RUN_STEPBACK_FRACTION, 1)
                t.long_run_km = stepback_km
                t.long_run_elev = round(
                    stepback_km * training_ratio
                    * PHASE_ELEV_FACTOR.get(t.phase, 1.0),
                    0,
                )
                plateau_len = 0
                # prev_peak unchanged so the wave resumes from the
                # previous peak on the next non-stepback week.
                continue
        else:
            plateau_len = 0
        prev_peak = t.long_run_km


# =========================================================================
# Layer 3: Daily distribution
# =========================================================================

def _intensity_for(workout_type: str, phase: str) -> str:
    """Return intensity label for a workout type and phase."""
    if workout_type == 'rest':
        return 'easy'
    if workout_type == 'strength':
        return 'moderate'
    if workout_type in ('recovery', 'easy', 'easy_pickups', 'easy_strides'):
        return 'easy'
    if workout_type == 'long_run':
        return 'moderate' if phase == 'Peak' else 'easy'
    if workout_type in ('intervals', 'tempo', 'uphill_intervals'):
        return 'hard'
    if workout_type in ('hill_repeats', 'vert_session'):
        return 'hard' if phase in ('Build', 'Peak') else 'moderate'
    if workout_type == 'descent_session':
        # Eccentric load is high but average HR stays moderate.
        return 'moderate'
    if workout_type == 'race_simulation':
        return 'race_pace'
    return 'easy'


# VK / uphill_only strength routine, phase-aware. Vert.run "How to Train for
# the Hills", Suunto "7 tips to accelerating your vertical speed", and
# Lavedrine 2024 "Running Your First VK" all converge on the same template:
# bilateral squats + single-leg step-ups + eccentric step-downs + calf raises
# + hip thrusts. Phase periodization (rep range / load) follows Lavedrine
# 2024: hypertrophy-leaning Base, max-strength Build, neuromuscular Peak.
# Without specific cues the slot was a coaching liability — athletes default
# to bench press or skip the session entirely (coach-review #47).
_VK_STRENGTH_TITLES = {
    'Base':     ('Strength — squats 3x8, step-ups 3x8, '
                 'calf raises 3x12 (build foundation)'),
    'Build':    ('Strength — squats 3x10 (heavier), step-downs 3x10 eccentric, '
                 'hip thrusts 3x8 (max strength)'),
    'Peak':     ('Strength — squats 3x6 (peak load), bounding 4x20m, '
                 'calf raises 3x15 (neuromuscular)'),
    'Recovery': 'Strength — light circuit: squats 2x10, step-ups 2x8, hip thrusts 2x10',
}


def _generate_title(
    workout_type: str, phase: str, km: float, elev: float,
    *, race_distance_km: float = 0, race_elevation_m: float = 0,
    race_type: str = 'loop',
) -> str:
    """Auto-generate workout title from type, phase, and parameters."""
    titles_static = {
        'rest': 'Rest day',
        'strength': 'Strength & conditioning',
        'recovery': 'Recovery run',
        'easy': 'Easy trail run',
        'easy_pickups': 'Easy run with pickups — 4x20sec strides',
        'easy_strides': 'Easy run with strides — 6x15sec',
    }
    if workout_type == 'strength' and race_type == 'uphill_only':
        return _VK_STRENGTH_TITLES.get(phase, titles_static['strength'])
    if workout_type in titles_static:
        return titles_static[workout_type]
    if workout_type == 'long_run':
        prefix = 'Race-simulation long run' if phase == 'Peak' else 'Long trail run'
        return f'{prefix} — {km:.0f}km with {elev:.0f}m D+'
    if workout_type == 'hill_repeats':
        return {
            'Base':  'Hill sprints — 6x10sec (neuromuscular power)',
            'Build': 'Hill repeats — 8x90sec (climbing strength)',
        }.get(phase, 'Z4 uphill repeats — 8x2min')
    if workout_type == 'intervals':
        # Peak keeps the uphill prescription for race-specificity; Build/Base
        # are flat threshold work (engine, not strength) — see Vert.run / Koop.
        # Edge case: Peak intervals can land on a non-mountain day when
        # mountain_days is narrow — fall back to the flat title rather than
        # promising climbs that aren't there.
        if _is_flat_prescription(workout_type, phase, km, elev):
            return 'Z3 threshold intervals: 4x8min flat/rolling'
        return 'Z4 power intervals: 3x5min uphill'
    if workout_type == 'tempo':
        return f'Tempo run — {km:.0f}km flat/rolling Z3 effort'
    if workout_type == 'uphill_intervals':
        # Rolling-terrain climbing threshold: VK / uphill_only downgrade
        # for hill_repeats / vert_session when no mountain day is available.
        # Coaching prescription: 4-5 × 6 min Z3 on a sustained rolling climb.
        return f'Uphill threshold intervals — 4x6min Z3 climbing ({elev:.0f}m D+)'
    if workout_type == 'vert_session':
        return f'Sustained climbing — {elev:.0f}m D+ vert session'
    if workout_type == 'descent_session':
        reps = {'Base': 3, 'Build': 4}.get(phase, 5)
        return (f'Descent practice — climb + {reps} controlled descents '
                f'({elev:.0f}m D+/D-)')
    if workout_type == 'race_simulation':
        if phase == 'Peak':
            return f'Race-simulation rehearsal — {km:.0f}km / {elev:.0f}m D+ at race effort'
        return f'RACE DAY — {race_distance_km:.0f}km / {race_elevation_m:.0f}m D+'
    return workout_type.replace('_', ' ').title()


DESCENT_BASE_START_WEEK = 3   # small doses start once the athlete has settled in


def _wants_descent_session(phase: str, week_number: int,
                           race_elevation_m: float,
                           steep_descent: bool = False) -> bool:
    """Whether this week should ship a structured descent session.

    Weekly from late Base (small dose) through Build and Peak. Prior downhill
    exposure (repeated-bout effect) is the main protection against downhill
    muscle damage and needs frequent small doses (Bontemps et al. 2020, Sports
    Med 50:2083; 2024 Eur J Sport Sci: 10 eccentric-biased sessions blunted
    soreness, 5 did not) - coach-review #112. The last Peak week (dress
    rehearsal) and Taper / Race never carry one, so the final 7-10+ days stay
    clear. Triggered when the race's cumulative D- (proxied by D+) is high or
    the course has a steep_descent key section.
    """
    if race_elevation_m < DESCENT_TRAINING_ELEV_THRESHOLD and not steep_descent:
        return False
    if phase in ('Peak', 'Build'):
        return True
    return phase == 'Base' and week_number >= DESCENT_BASE_START_WEEK


def _select_workouts_for_phase(
    phase: str, n_training_days: int, athlete_category: str,
    week_number: int, back_to_back: bool,
    *,
    inject_descent_session: bool = False,
    race_type: str = 'loop',
    polarized: bool = False,
) -> list[str]:
    """Pick the workout types for this phase's non-rest training days.

    Length == n_training_days, ordered by importance.
    """
    catalog = [w for w in PHASE_CATALOG.get(phase, PHASE_CATALOG['Base'])
               if w != 'rest']

    # VK / uphill_only specificity bias: in Build phase the canonical catalog
    # ships a flat ``tempo`` slot, but for an all-uphill race a flat threshold
    # session has low transfer. Vert.run / Suunto / Lavedrine 2024 prescribe
    # 2 uphill workouts per week year-round for VK athletes — replace tempo
    # with hill_repeats so the Build phase keeps the climbing-strength
    # stimulus that's already in Base. Peak already runs vert_session +
    # uphill intervals (see ``_is_flat_prescription``) so it needs no edit.
    if race_type == 'uphill_only' and phase == 'Build' and 'tempo' in catalog:
        catalog[catalog.index('tempo')] = 'hill_repeats'

    if polarized and phase == 'Build' and 'tempo' in catalog:
        catalog[catalog.index('tempo')] = 'intervals'

    # Race-specific descent practice swaps in for the lower-priority hard
    # workout (tempo in Build, intervals in Peak). Replacing an existing
    # hard rather than adding a third keeps the canonical 2-hard-per-week
    # cap intact while still injecting eccentric specificity. Coaching
    # rationale: for races with ≥1500 m D-, descent technique and quad
    # eccentric tolerance outrank generic flat threshold or VO2 power.
    # Weekly descent (coach-review #112) must not erase the Build quality slot:
    # odd Build weeks give up hill_repeats instead (the descent session climbs
    # back up its own D-), so tempo / VO2 intervals survive every other week.
    if inject_descent_session and 'descent_session' not in catalog:
        order = ('tempo', 'intervals', 'easy')
        if phase == 'Build' and week_number % 2:
            order = ('hill_repeats',) + order
        for target in order:
            if target in catalog:
                catalog[catalog.index(target)] = 'descent_session'
                break

    # Cat 1 restriction: no Z3+/intensity until week 4. Tempo and intervals
    # both qualify as Z3+ and are filtered together. descent_session is
    # eccentric strength, not Z3+ — kept available to cat_1 from week 1.
    if athlete_category == 'cat_1' and week_number < CAT1_INTENSITY_WEEK:
        catalog = [w for w in catalog if w not in ('intervals', 'tempo')]

    if len(catalog) > n_training_days:
        priority = {
            'race_simulation': 0, 'long_run': 1,
            'hill_repeats': 2, 'vert_session': 3,
            'descent_session': 3,
            'intervals': 4, 'tempo': 4,
            'easy_pickups': 5, 'easy_strides': 5,
            'easy': 6, 'recovery': 7,
        }
        catalog.sort(key=lambda w: priority.get(w, 8))
        catalog = catalog[:n_training_days]
    while len(catalog) < n_training_days:
        catalog.append('easy')
    return catalog


def _enforce_mountain_budget(
    workouts: list[str], training_days: list[str],
    mountain_set: set[str] | None, mountain_budget: float | None,
    week_number: int, phase: str,
    *,
    race_type: str = 'loop',
) -> tuple[list[str], int, int]:
    """Demote excess mountain workouts to flat alternatives.

    Two pressures: (a) not enough mountain-eligible days in the calendar,
    (b) weekly mountain budget cap (per_week / per_month / mountain_days fallback).
    """
    # Calendar pressure (mountain_set): only sessions that actually need a
    # mountain day count toward the deficit. Base hill_repeats are 80 m D+
    # sprints and fit on any terrain.
    needs_day = lambda w: _needs_mountain_day(w, phase)
    # Budget pressure (mountain_access_per_week): legacy semantics — every
    # workout in MOUNTAIN_WORKOUTS counts. A user with zero mountain access
    # still sees Base hill_repeats downgraded.
    counts_for_budget = lambda w: w in MOUNTAIN_WORKOUTS

    original = sum(1 for w in workouts if counts_for_budget(w))
    downgraded = 0

    if mountain_set is not None:
        slots = sum(1 for d in training_days if d in mountain_set)
        excess = max(0, sum(1 for w in workouts if needs_day(w)) - slots)
        # Coaching-priority for which mountain workout to KEEP when budget is
        # tight. Drop the LEAST race-specific first. For ultra-trail prep with
        # ≥1500 m D-, the long_run already delivers most generic climb stimulus
        # (hill_repeats / vert_session); descent_session is the only session
        # that trains downhill eccentric quad tolerance — irreplaceable.
        # Without this, Sat+Sun mountain users with Sun=long_run see descent
        # silently downgraded to easy on every Build/Peak week, defeating the
        # `_wants_descent_session` injection. (Vert.run, Koop, Roche).
        keep_priority = {
            'descent_session': 3,  # keep last (most race-specific)
            'vert_session': 2,
            'hill_repeats': 1,     # drop first (most generic)
        }
        for _ in range(excess):
            target_idx = None
            target_p = None
            for i, w in enumerate(workouts):
                if not needs_day(w):
                    continue
                p = keep_priority.get(w, 0)
                if target_p is None or p < target_p:
                    target_idx = i
                    target_p = p
            if target_idx is None:
                break
            workouts[target_idx] = _downgrade_target(
                workouts[target_idx], phase, workouts,
                race_type=race_type,
            )
            downgraded += 1

    if mountain_budget is not None:
        if 0 < mountain_budget < 1:
            cycle = max(1, round(1.0 / mountain_budget))
            allowed = 1 if (week_number % cycle == 0) else 0
        else:
            allowed = max(0, int(mountain_budget))
        used = 0
        for i, w in enumerate(workouts):
            if counts_for_budget(w):
                if used >= allowed:
                    workouts[i] = _downgrade_target(
                        w, phase, workouts, race_type=race_type,
                    )
                    downgraded += 1
                else:
                    used += 1

    return workouts, original, downgraded


def _hard_day_assignment(
    hard: list[str], training_days: list[str], anchor_days: list[str],
    mountain_set: set[str] | None, phase: str, long_run_day: str,
) -> dict[str, str]:
    """Pick the assignment of hard workouts to training days that maximizes
    the minimum cyclic gap between any two hard sessions (anchor_days
    included as fixed hard sessions).

    With ≤ 4 hard workouts and ≤ 6 training days this is at most a few
    hundred evaluations — much simpler than a custom heuristic and always
    finds the optimal spacing. Returns {day: workout}.

    Cross-week recovery: cyclic distance treats Mon-after-Sun-LR and
    Sat-before-Sun-LR as equally 1 day away, but in real calendar time
    Mon-after-LR carries the previous week's LR fatigue (insufficient
    recovery) while Sat-before-LR is a normal back-to-back stack. The
    score breaks this tie by penalising placements on the day immediately
    after ``long_run_day``.
    """
    from itertools import combinations, permutations

    if not hard:
        return {}

    post_lr_day = DAYS_OF_WEEK[(_day_offset(long_run_day) + 1) % 7]
    # Day immediately AFTER the back-to-back stack (post_lr_day + 1, e.g. Mon
    # when LR=Sat). Used as a tertiary tie-break: when min_gap is dominated
    # by an unavoidable LR + post-LR-mountain-hard pair (gap=1), we still
    # want to keep the day after that stack hard-free so the runner gets at
    # least one easy day before the next hard session. Without this the
    # iteration order can pick a Mon-tempo and produce 3 hard days in a row
    # (Sat/Sun/Mon) — coaching consensus is ≥ 48 h between hard sessions.
    post_post_lr_day = DAYS_OF_WEEK[(_day_offset(long_run_day) + 2) % 7]
    anchor_set = set(anchor_days)

    def eligible_days(w: str) -> set[str]:
        if mountain_set is not None and _needs_mountain_day(w, phase):
            return set(d for d in training_days if d in mountain_set)
        return set(training_days)

    def mountain_preference(perm: tuple[str, ...], combo: tuple[str, ...]) -> int:
        """Soft preference: Peak intervals prefer mountain-eligible days
        (otherwise the prescription falls back to flat). Returns count of
        Peak-intervals slots that landed on a mountain day. Zero when
        ``mountain_set`` is None (every day is mountain-eligible)."""
        if mountain_set is None or phase != 'Peak':
            return 0
        return sum(
            1 for w, d in zip(perm, combo)
            if w == 'intervals' and d in mountain_set
        )

    best: dict[str, str] = {}
    # Score tuple: (-post_lr_penalty, -post_b2b_penalty, mountain_preference,
    # combo_internal_gap, min_gap). Lexicographic — first avoid stacking a
    # hard right after the previous LR (cross-week recovery), then avoid
    # 3-hard-in-a-row when an LR + post-LR pair is unavoidable, then prefer
    # mountain placement for race-specific uphill stimulus, then keep the
    # placed hards apart from each other (within-combo gap), then maximise
    # spacing including anchors.
    #
    # Why combo_internal_gap: when a free-day calendar is dense (e.g. a
    # mountain-ultra with strength on Tue + rest on Fri leaves only 4 free
    # days) the anchor pair LR-Sun ↔ Mon will always force min_gap=1, so
    # min_gap alone can't distinguish (Wed, Thu) — adjacent hards! — from
    # (Mon, Thu) — non-adjacent hards. Adding combo_internal_gap as an
    # earlier tie-break prevents the optimizer from picking Wed-Thu.
    best_score: tuple[int, int, int, int, int] = (-99, -99, -1, -1, -1)
    for combo in combinations(training_days, len(hard)):
        for perm in permutations(hard):
            if not all(d in eligible_days(w) for w, d in zip(perm, combo)):
                continue
            anchors = list(anchor_days) + list(combo)
            min_gap = min(
                _day_distance(a, b)
                for i, a in enumerate(anchors)
                for b in anchors[i + 1:]
            ) if len(anchors) >= 2 else 7
            combo_internal_gap = min(
                _day_distance(a, b)
                for i, a in enumerate(combo)
                for b in combo[i + 1:]
            ) if len(combo) >= 2 else 7
            post_lr_count = sum(1 for d in combo if d == post_lr_day)
            # post_b2b only matters when there's actually a hard pinned on
            # post_lr_day (either via this combo or via a pre-existing
            # anchor). If post_lr_day is empty, there's no back-to-back
            # stack to recover from and the post_post_lr_day slot is free
            # to take a hard session.
            post_lr_pinned = post_lr_count > 0 or post_lr_day in anchor_set
            post_b2b_count = (sum(1 for d in combo if d == post_post_lr_day)
                              if post_lr_pinned else 0)
            score = (-post_lr_count, -post_b2b_count,
                     mountain_preference(perm, combo),
                     combo_internal_gap, min_gap)
            if score > best_score:
                best_score = score
                best = dict(zip(combo, perm))
    return best


def _place_workouts(
    workouts: list[str], training_days: list[str], day_slots: dict[str, str | None],
    long_run_day: str, mountain_set: set[str] | None,
    back_to_back: bool, phase: str,
) -> dict[str, str | None]:
    """Place workouts on training days under separation constraints.

    Hard sessions are placed first using ``_hard_day_assignment`` which
    finds the assignment maximising min-gap to long-run and to other hard
    sessions. ``back_to_back`` intentionally pins one hard the day before
    the long run before optimal spacing kicks in.
    """
    hard = [w for w in workouts if w in HARD_WORKOUTS]
    easy = [w for w in workouts if w not in HARD_WORKOUTS]

    # Back-to-back: pin one hard session the day before long run.
    # BTB-anchor priority: pick the most race-specific hard for the Sat slot
    # so the (Sat-mountain + Sun-long_run) stack carries the strongest
    # specificity signal — this is the canonical mountain-ultra "money
    # workout" (Vert.run, Koop, Roche). Order: descent_session > vert_session
    # > hill_repeats > tempo > intervals. Without explicit priority,
    # ``hard.pop(0)`` would consume whichever workout the upstream sort put
    # first (typically hill_repeats / intervals) and orphan descent_session,
    # which then has no mountain day available and falls through to easy —
    # silently defeating ``_wants_descent_session`` injection.
    fixed_hard_days: list[str] = [long_run_day]
    if back_to_back and phase in ('Build', 'Peak') and hard:
        prev = DAYS_OF_WEEK[(_day_offset(long_run_day) - 1) % 7]
        if prev in training_days:
            btb_priority = {
                'descent_session': 0, 'vert_session': 1,
                'hill_repeats': 2, 'uphill_intervals': 3,
                'tempo': 4, 'intervals': 5,
            }
            sat_is_mountain = mountain_set is None or prev in mountain_set
            eligible = [
                w for w in hard
                if sat_is_mountain or not _needs_mountain_day(w, phase)
            ]
            if eligible:
                chosen = min(eligible, key=lambda w: btb_priority.get(w, 5))
                hard.remove(chosen)
                day_slots[prev] = chosen
                training_days.remove(prev)
                fixed_hard_days.append(prev)

    # Hard placement with optimal spacing (mountain-only on mountain days).
    assignment = _hard_day_assignment(
        hard, training_days, fixed_hard_days, mountain_set, phase, long_run_day,
    )
    for d, w in assignment.items():
        day_slots[d] = w
        training_days.remove(d)

    # Hard workouts that couldn't be placed (e.g. no mountain-eligible day
    # available) fall through to an easy session.
    unplaced = len(hard) - len(assignment)
    easy.extend(['easy'] * unplaced)

    # Easy / recovery: sort by descending distance from long run so the
    # hardest easy slots stay closer to the weekend.
    training_days.sort(key=lambda d: _day_distance(d, long_run_day), reverse=True)
    for ew in easy:
        if not training_days:
            break
        day_slots[training_days.pop(0)] = ew

    # Anything left becomes rest.
    for d in DAYS_OF_WEEK:
        if day_slots[d] is None:
            day_slots[d] = 'rest'
    return day_slots


def _density_cap_for(workout_type: str, phase: str) -> float:
    """Per-workout density ceiling. Flat intensity sessions
    (tempo, Build/Base intervals) override the regular cap — they're
    threshold/VO2max stimulus, not strength work. Race-week shakeouts
    are clamped to RACE_WEEK_DENSITY_CAP to avoid pre-race eccentric load
    (race_simulation itself is exempt — it's the race)."""
    if phase == 'Race' and workout_type != 'race_simulation':
        return min(RACE_WEEK_DENSITY_CAP, MAX_ELEV_DENSITY)
    if _is_flat_intensity(workout_type, phase):
        return min(FLAT_INTENSITY_DENSITY_CAP, MAX_ELEV_DENSITY)
    cap = WORKOUT_DENSITY_CAP.get(workout_type, MAX_ELEV_DENSITY)
    return min(cap, MAX_ELEV_DENSITY)


def _density_for(workout_type: str, training_ratio: float, phase: str) -> float:
    """Per-workout elevation density (m D+ / km), capped both globally and
    by workout-type ceiling. Phase-aware for tempo / intervals. Race-week
    shakeouts (everything except race_simulation) are flattened to
    RACE_WEEK_DENSITY_CAP per coach-review #5."""
    if phase == 'Race' and workout_type != 'race_simulation':
        return min(RACE_WEEK_DENSITY_CAP, MAX_ELEV_DENSITY)
    if _is_flat_intensity(workout_type, phase):
        return min(FLAT_INTENSITY_MULTIPLIER * training_ratio,
                   FLAT_INTENSITY_DENSITY_CAP, MAX_ELEV_DENSITY)
    mult = ELEV_MULTIPLIER.get(workout_type, 0.5)
    density = training_ratio * mult
    cap = WORKOUT_DENSITY_CAP.get(workout_type, MAX_ELEV_DENSITY)
    return min(density, cap, MAX_ELEV_DENSITY)


def _drop_unfittable_easy_days(
    placed: dict[str, str], non_fixed: list[str], remaining_km: float,
    phase: str = '',
) -> list[str]:
    """When the budget can't fit every non-fixed day at its coaching
    minimum, drop easy/recovery days (convert to rest) — never hard
    sessions. A 4 km "easy" run is not useful aerobic stimulus; a rest
    day is. Mutates ``placed`` in place and returns the trimmed
    ``non_fixed`` list.

    Drop order: plain ``easy`` and ``recovery`` are dropped before
    ``easy_pickups`` / ``easy_strides`` because the latter carry a
    deliberate neuromuscular stimulus (taper sharpening, race-week
    shakeout). Mujika & Padilla (2003) and Magness all stress that
    intensity must be preserved through the taper while volume drops.
    """
    drop_order = ('recovery', 'easy', 'easy_pickups', 'easy_strides')
    while True:
        total_min = sum(
            _km_range_for(placed[d], phase)[0] for d in non_fixed
        )
        if total_min <= remaining_km:
            return non_fixed
        # Find an easy/recovery day to drop, by drop_order priority.
        for wt in drop_order:
            target = next((d for d in non_fixed if placed[d] == wt), None)
            if target is not None:
                placed[target] = 'rest'
                non_fixed = [d for d in non_fixed if d != target]
                break
        else:
            # No droppable easy day left — only hard sessions remain.
            return non_fixed


# Workouts whose upper km bound must be strict (no 30 % allocation
# headroom). These are "shakeout / pickups" sessions defined by their
# brevity: a 14 km easy_pickups in race-week / late-Taper is no longer
# a pickups workout, it's a normal endurance run that depletes glycogen
# 5–7 days before race day (Magness, Hudson, Pfitzinger; Mujika & Padilla
# 2003 taper review). Without a strict cap, ``_size_distances`` floods
# the only non-fixed Taper-2 day with all leftover budget, shipping a
# 14 km "pickups" — coach-review #46.
_STRICT_UPPER_KM_TYPES = ('easy_pickups', 'easy_strides')


def _size_distances(
    non_fixed_days: list[str], placed: dict[str, str], remaining_km: float,
    phase: str = '',
) -> dict[str, float]:
    """Allocate remaining_km across non-fixed days.

    Each day floors at WORKOUT_KM_RANGE[wt].lo (the coaching-useful
    minimum: easy ≥ 6 km, hill ≥ 8 km, etc.). Caller is expected to
    have already dropped easy days that don't fit (see
    ``_drop_unfittable_easy_days``); when the surviving minimums still
    exceed remaining_km, total weekly volume will overshoot — that's
    coach-correct preferable to chopping easy runs in half."""
    raw: dict[str, float] = {}
    for d in non_fixed_days:
        lo, hi = _km_range_for(placed[d], phase)
        raw[d] = (lo + hi) / 2.0
    total = sum(raw.values())
    if total <= 0 or not non_fixed_days:
        return raw
    scale = remaining_km / total
    for d in non_fixed_days:
        wt = placed[d]
        lo, hi = _km_range_for(wt, phase)
        # Pickups / strides workouts are defined by their brevity — no
        # 30 % allocation headroom or they degenerate into endurance runs
        # in low-volume weeks (coach-review #46).
        upper = float(hi) if wt in _STRICT_UPPER_KM_TYPES else hi * 1.3
        raw[d] = max(float(lo), min(upper, raw[d] * scale))
    return raw


def _size_elevations(
    non_fixed_days: list[str], placed: dict[str, str], distances: dict[str, float],
    *,
    training_ratio: float, remaining_elev: float,
    mountain_set: set[str] | None,
    phase: str,
    terrain_profile: str | None = None,
) -> dict[str, float]:
    """Distribute remaining_elev across non-fixed days.

    Hill-repeats use a deterministic profile (overrides density). Flat-day
    elevations are fixed at FLAT_CITY_ELEV_DENSITY when mountain_set is set;
    mountain-day budgets absorb the rest. Tempo and Build/Base intervals
    are kept flat regardless of mountain access.

    Mountain / rolling_hills caveat: ``mountain_set`` restricts where MOUNTAIN
    workouts can land (calendar availability) — it does NOT mean the rest of
    the week is on flat ground. Athletes with terrain_profile=='mountain' or
    'rolling_hills' have rolling terrain available every day, just no time
    for a structured mountain workout. So midweek easy-day density tracks
    the workout's normal multiplier instead of being clipped to the flat-
    city 5 m/km. Only true ``flat_urban`` runners hit FLAT_CITY_ELEV_DENSITY
    on non-mountain-set days (issue #35).
    """
    elev: dict[str, float] = {}
    # Workouts whose elevation comes from a deterministic profile (set in
    # ``_build_day_dicts``) are skipped here — their D+ doesn't depend on
    # the weekly elevation budget.
    deterministic = ('hill_repeats', 'descent_session')
    has_terrain = terrain_profile in ('rolling_hills', 'mountain')
    for d in non_fixed_days:
        wt = placed[d]
        is_mtn = (mountain_set is None or d in mountain_set)
        if wt in deterministic:
            elev[d] = 0.0  # placeholder; final value set in build_days
        elif _is_flat_intensity(wt, phase):
            elev[d] = distances[d] * _density_for(wt, training_ratio, phase)
        elif not is_mtn and not has_terrain:
            # Genuinely flat training environment.
            elev[d] = distances[d] * FLAT_CITY_ELEV_DENSITY
        else:
            elev[d] = distances[d] * _density_for(wt, training_ratio, phase)

    if mountain_set is not None:
        flat_total = sum(elev[d] for d in non_fixed_days if d not in mountain_set)
        mtn_days = [d for d in non_fixed_days if d in mountain_set
                    and placed[d] not in deterministic
                    and not _is_flat_intensity(placed[d], phase)]
        budget = max(0, remaining_elev - flat_total)
        raw_total = sum(elev.get(d, 0) for d in mtn_days)
        if raw_total > 0 and budget > 0:
            scale = budget / raw_total
            for d in mtn_days:
                elev[d] *= scale
                if distances[d] > 0:
                    cap = _density_cap_for(placed[d], phase)
                    if elev[d] / distances[d] > cap:
                        elev[d] = distances[d] * cap
    else:
        # No mountain set defined: scale non-deterministic, non-flat-intensity days to fit budget.
        non_hill = [d for d in non_fixed_days
                    if placed[d] not in deterministic
                    and not _is_flat_intensity(placed[d], phase)]
        total = sum(elev[d] for d in non_hill)
        if total > 0 and remaining_elev > 0:
            scale = remaining_elev / total
            for d in non_hill:
                elev[d] *= scale
                if distances[d] > 0:
                    cap = _density_cap_for(placed[d], phase)
                    if elev[d] / distances[d] > cap:
                        elev[d] = distances[d] * cap

    return elev


def _redistribute_elevation(
    days: list[dict], phase: str,
    *,
    terrain_profile: str | None = None,
) -> tuple[list[dict], float, float]:
    """Snap low-density easy / recovery / flat-intensity days to flat and
    pour the saved budget onto climb-focused days.

    On mountain plans (terrain_profile=='mountain'), plain ``easy`` keeps
    its rolling D+ — only the explicitly-flat workout types (easy_pickups
    / easy_strides / recovery / flat-intensity) flatten. This preserves
    midweek climb stimulus on mountain plans (issue #35).

    Returns (days, residual_unused, originally_planned_total).
    """
    originally_planned = sum(float(d.get('elevation_m') or 0) for d in days)
    flatten_set = (ELEV_FLATTEN_TYPES_MOUNTAIN
                   if terrain_profile == 'mountain'
                   else ELEV_FLATTEN_TYPES)

    saved = 0.0
    for d in days:
        wt = d.get('workout_type')
        km = float(d.get('distance_km') or 0)
        elev = float(d.get('elevation_m') or 0)
        flattenable = (
            wt in flatten_set
            or _is_flat_intensity(wt, phase)
            or _is_flat_prescription(wt, phase, km, elev)
        )
        if not flattenable:
            continue
        if km <= 0 or elev <= 0:
            continue
        if elev / km < MIN_MEANINGFUL_ELEV_DENSITY:
            saved += elev
            d['elevation_m'] = 0.0
            tag = '[flat — pace focus, ignore elevation]'
            d['notes'] = (f"{d.get('notes') or ''} {tag}").strip()

    if saved <= 0:
        return days, 0.0, originally_planned

    sinks = [d for d in days if d.get('workout_type') in ELEV_SINK_TYPES]
    if not sinks:
        return days, saved, originally_planned

    weights = [ELEV_MULTIPLIER.get(d['workout_type'], 0) for d in sinks]
    total_w = sum(weights) or 1.0

    residual = saved
    for d, w in zip(sinks, weights):
        share = saved * (w / total_w)
        km = float(d.get('distance_km') or 0)
        current = float(d.get('elevation_m') or 0)
        cap = MAX_ELEV_DENSITY * km if km > 0 else current + share
        addable = max(0.0, cap - current)
        applied = min(share, addable)
        d['elevation_m'] = round(current + applied)
        residual -= applied

    return days, max(0.0, residual), originally_planned


def _clamp_day_elev(
    day_name: str, workout_type: str, km: float, elev: float,
    *,
    midweek_cap: float | None,
    max_mountain_elevation_m: float | None,
    treadmill_set: frozenset | set = frozenset(),
) -> float:
    """Apply every elevation cap (density, midweek, mountain-outing) to a
    single day. Idempotent — safe to run repeatedly."""
    if workout_type in ('long_run', 'race_simulation', 'rest', 'strength'):
        return elev
    if km > 0 and elev / km > MAX_ELEV_DENSITY:
        elev = km * MAX_ELEV_DENSITY
    # flat_urban has no terrain for structured climbs: keep its cap on them.
    exempt = (workout_type in MIDWEEK_CAP_EXEMPT and midweek_cap is not None
              and midweek_cap > MIDWEEK_ELEV_CAP['flat_urban'])
    if (midweek_cap is not None and day_name in MIDWEEK_DAYS
            and day_name not in treadmill_set and not exempt
            and elev > midweek_cap):
        elev = float(midweek_cap)
    if (max_mountain_elevation_m is not None and workout_type in MOUNTAIN_WORKOUTS
            and elev > max_mountain_elevation_m):
        elev = float(max_mountain_elevation_m)
    return elev


def _build_day_dicts(
    placed: dict[str, str],
    *,
    long_run_km: float, long_run_elev: float, long_run_is_mountain: bool,
    race_sim_km: float, race_sim_elev: float,
    distances: dict[str, float], elevations: dict[str, float],
    phase: str, training_ratio: float,
    midweek_cap: float | None,
    max_mountain_elevation_m: float | None,
    race_distance_km: float, race_elevation_m: float,
    race_type: str = 'loop',
    treadmill_set: frozenset | set = frozenset(),
) -> list[dict]:
    """Materialize the (day, workout, km, elev) tuples into dicts."""
    days: list[dict] = []
    for d in DAYS_OF_WEEK:
        wt = placed[d]
        if wt == 'long_run':
            km = long_run_km
            elev = (long_run_elev if long_run_is_mountain
                    else long_run_km * FLAT_CITY_ELEV_DENSITY)
            if km > 0 and elev / km > MAX_ELEV_DENSITY:
                elev = km * MAX_ELEV_DENSITY
        elif wt == 'race_simulation':
            km, elev = race_sim_km, race_sim_elev
        elif wt in ('rest', 'strength'):
            km, elev = 0.0, 0.0
        elif wt == 'hill_repeats':
            # Deterministic phase-specific size (sprint power vs. climbing strength).
            km, elev = HILL_REPEATS_PROFILE.get(
                phase, HILL_REPEATS_PROFILE['Build'],
            )
        elif wt == 'descent_session':
            # Deterministic profile: sized so D- ≈ D+ for symmetric eccentric load.
            km, elev = DESCENT_SESSION_PROFILE.get(
                phase, DESCENT_SESSION_PROFILE['Build'],
            )
        elif wt == 'easy_strides' and phase in ('Race', 'Peak'):
            # Day-before-race / day-before-dress-rehearsal shakeout: 4 km
            # flat + strides. Coaching consensus (Magness, Hudson, Pfitzinger,
            # Mujika & Padilla): zero D+ the day before — climbing 24 h before
            # a race-effort session leaves quad fatigue that can't be cleared.
            # Peak-phase easy_strides only appears via the explicit pin in the
            # last Peak week (dress rehearsal); regular Peak weeks don't carry
            # this workout type.
            km, elev = 4.0, 0.0
        else:
            km = distances.get(d, 0.0)
            elev = elevations.get(d, 0.0)

        elev = _clamp_day_elev(
            d, wt, km, elev,
            midweek_cap=midweek_cap,
            max_mountain_elevation_m=max_mountain_elevation_m,
            treadmill_set=treadmill_set,
        )

        days.append({
            'day': d,
            'date': '',
            'workout_type': wt,
            'title': _generate_title(
                wt, phase, km, elev,
                race_distance_km=race_distance_km, race_elevation_m=race_elevation_m,
                race_type=race_type,
            ),
            'distance_km': round(km, 1),
            'elevation_m': round(elev, 0),
            'intensity': _intensity_for(wt, phase),
            'notes': '',
            'route_id': None,
            'route_match_quality': 'pending',
            'suggested_alternatives': [],
        })
    return days


def _reapply_elev_caps(
    days: list[dict],
    *,
    midweek_cap: float | None,
    max_mountain_elevation_m: float | None,
    treadmill_set: frozenset | set = frozenset(),
) -> None:
    """After elevation redistribution, sink days may have absorbed budget
    that pushes them past midweek/mountain caps. Re-clamp in place."""
    for day in days:
        elev = float(day.get('elevation_m') or 0)
        capped = _clamp_day_elev(
            day['day'], day['workout_type'],
            float(day.get('distance_km') or 0), elev,
            midweek_cap=midweek_cap,
            max_mountain_elevation_m=max_mountain_elevation_m,
            treadmill_set=treadmill_set,
        )
        if capped < elev:
            day['elevation_m'] = round(capped)


def _race_regime_cap(race_distance_km: float) -> tuple[float, float]:
    """Return (km_fraction, elev_fraction) for the back-to-back weekend
    based on race distance. See ``RACE_REGIME_WEEKEND_CAPS`` for the table."""
    for max_km, km_frac, elev_frac in RACE_REGIME_WEEKEND_CAPS:
        if race_distance_km <= max_km:
            return km_frac, elev_frac
    return RACE_REGIME_WEEKEND_CAPS[-1][1], RACE_REGIME_WEEKEND_CAPS[-1][2]


def _apply_regime_weekend_cap(
    days: list[dict], long_run_day: str, phase: str,
    race_distance_km: float, race_elevation_m: float,
    race_type: str = 'loop',
) -> None:
    """Trim the (long_run_day - 1, long_run_day) pair so the back-to-back
    weekend respects the race-distance regime cap.

    Only the day-before-long-run is shrunk: the long run carries the primary
    specificity stimulus and is sized by ``compute_weekly_targets``. When the
    pre-LR day is a hard session (vert_session, hill_repeats, intervals,
    tempo), trimming km/elev keeps the workout type but reduces volume; if
    the trim would leave it below ``REGIME_HARD_FLOOR_*``, the workout is
    converted to ``easy`` to avoid a degenerate prescription.

    Skipped on Race / Recovery / Taper / Base weeks: race week's race
    simulation is the actual race, recovery and taper are intentional
    deloads, and Base weeks rarely produce a stacked weekend.

    Skipped for VK / uphill_only races: race_distance (≤ 5 km) is far too
    short to anchor the cap. With race_distance = 5 km the marathon-tier
    formula yields weekend_km_cap = 0.95 × 5 = 4.75 km, which the long_run
    alone consumes — the cap then trims the Sat hill_repeats to ``easy``
    and silently kills the canonical Sat-hill + Sun-long-mountain VK
    weekend stack (Vert.run, Suunto). Volume control for VK weekends is
    already enforced upstream by ``max_weekly_km`` and the per-workout
    distance ranges; the regime cap is meaningful only when the race
    distance itself is the dominant volume reference.
    """
    if phase not in ('Build', 'Peak'):
        return
    if race_distance_km <= 0:
        return
    if race_type == 'uphill_only':
        return
    km_frac, elev_frac = _race_regime_cap(race_distance_km)
    weekend_km_cap = race_distance_km * km_frac
    weekend_elev_cap = race_elevation_m * elev_frac

    prev_day = DAYS_OF_WEEK[(_day_offset(long_run_day) - 1) % 7]
    long_run_d = next((d for d in days if d['day'] == long_run_day), None)
    prev_d = next((d for d in days if d['day'] == prev_day), None)
    if not (long_run_d and prev_d):
        return
    # Only the back-to-back configuration produces the over-aggressive
    # weekend; if the pre-LR day is rest/easy/strength, the cap is moot.
    if prev_d['workout_type'] not in HARD_WORKOUTS:
        return
    if long_run_d['workout_type'] not in ('long_run', 'race_simulation'):
        return

    long_run_km = float(long_run_d.get('distance_km') or 0)
    long_run_elev = float(long_run_d.get('elevation_m') or 0)
    prev_km = float(prev_d.get('distance_km') or 0)
    prev_elev = float(prev_d.get('elevation_m') or 0)

    weekend_km = long_run_km + prev_km
    weekend_elev = long_run_elev + prev_elev
    over_km = weekend_km > weekend_km_cap + 0.5
    over_elev = weekend_elev > weekend_elev_cap + 50.0
    if not (over_km or over_elev):
        return

    new_prev_km = max(0.0, weekend_km_cap - long_run_km) if over_km else prev_km
    new_prev_elev = max(0.0, weekend_elev_cap - long_run_elev) if over_elev else prev_elev

    # If the trim leaves the hard session below the coaching-meaningful
    # floor, swap to ``easy``: a 5 km / 100 m vert_session is dishonest.
    if new_prev_km < REGIME_HARD_FLOOR_KM or new_prev_elev < REGIME_HARD_FLOOR_ELEV:
        prev_d['workout_type'] = 'easy'
        prev_d['intensity'] = _intensity_for('easy', phase)
        # Clamp to the easy band so sizing stays coherent.
        easy_lo, easy_hi = WORKOUT_KM_RANGE['easy']
        new_prev_km = min(max(new_prev_km, easy_lo), easy_hi)
        # An easy day should not carry race-D+ density.
        new_prev_elev = min(new_prev_elev, new_prev_km * FLAT_CITY_ELEV_DENSITY)

    prev_d['distance_km'] = round(new_prev_km, 1)
    prev_d['elevation_m'] = round(new_prev_elev, 0)
    prev_d['title'] = _generate_title(
        prev_d['workout_type'], phase, new_prev_km, new_prev_elev,
        race_distance_km=race_distance_km, race_elevation_m=race_elevation_m,
        race_type=race_type,
    )


# Coaching rule: never more than two consecutive days of complete rest
# (≥3 in a row triggers detraining and stiffness without a clear adaptation
# benefit). Race / Taper weeks are the typical violators because the
# catalog ships with 4 rest slots.
MAX_CONSECUTIVE_REST_DAYS = 2

# Sizing for the shakeout day inserted to break an over-long rest run.
# Phase-aware: race week gets a true micro-shakeout (strides), taper /
# recovery get a slightly longer easy effort.
_SHAKEOUT_SPEC = {
    'Race':     ('easy_strides', 5.0,  50.0),
    'Taper':    ('easy',         8.0, 100.0),
    'Recovery': ('recovery',     8.0, 150.0),
}
_SHAKEOUT_DEFAULT = ('recovery', 8.0, 150.0)


def _convert_rest_to_shakeout(
    day: dict, phase: str,
    *, race_distance_km: float, race_elevation_m: float,
    race_type: str = 'loop',
) -> None:
    """Mutate a rest day into a short opener / shakeout in place."""
    wt, km, elev = _SHAKEOUT_SPEC.get(phase, _SHAKEOUT_DEFAULT)
    day['workout_type'] = wt
    day['distance_km'] = km
    day['elevation_m'] = elev
    day['intensity'] = _intensity_for(wt, phase)
    day['title'] = _generate_title(
        wt, phase, km, elev,
        race_distance_km=race_distance_km,
        race_elevation_m=race_elevation_m,
        race_type=race_type,
    )
    day['notes'] = ''


def _enforce_max_consecutive_rest(
    days: list[dict], phase: str, rest_days: list[str],
    *, race_distance_km: float, race_elevation_m: float,
    max_consecutive: int = MAX_CONSECUTIVE_REST_DAYS,
    race_type: str = 'loop',
) -> None:
    """Break runs of more than ``max_consecutive`` rest days by inserting
    a short shakeout in the middle of the over-long run.

    Honors user-chosen rest days when possible: if the run contains both
    user-chosen and engine-generated rests, an engine-rest is converted
    first. Race week's Mon–Fri all-rest pattern is the canonical case
    this rule fixes.
    """
    user_rests = set(rest_days or ())
    # Bounded by week length; in practice 1 conversion (sometimes 2) suffices.
    for _ in range(len(days)):
        run_start = None
        target_idx = None
        for idx, day in enumerate(days):
            if day['workout_type'] == 'rest':
                if run_start is None:
                    run_start = idx
                if idx - run_start + 1 > max_consecutive:
                    target_idx = idx
                    break
            else:
                run_start = None
        if target_idx is None:
            return
        candidates = list(range(run_start, target_idx + 1))
        non_user = [k for k in candidates if days[k]['day'] not in user_rests]
        chosen = (non_user[len(non_user) // 2] if non_user
                  else candidates[len(candidates) // 2])
        _convert_rest_to_shakeout(
            days[chosen], phase,
            race_distance_km=race_distance_km,
            race_elevation_m=race_elevation_m,
            race_type=race_type,
        )


def _round_and_refresh_titles(
    days: list[dict], phase: str,
    race_distance_km: float, race_elevation_m: float,
    *, race_type: str = 'loop', polarized: bool = False,
) -> None:
    """Final pass: snap distance / elevation to coaching granularity
    (50 m D+ steps, min 100 m; even km steps except for long_run /
    race_simulation) and regenerate titles so they reflect the rounded
    numbers."""
    for day in days:
        wt = day['workout_type']
        day['distance_km'] = _round_km(
            float(day.get('distance_km') or 0), wt,
        )
        day['elevation_m'] = _round_elev(float(day.get('elevation_m') or 0))
        day['title'] = _generate_title(
            wt, phase,
            float(day.get('distance_km') or 0),
            float(day.get('elevation_m') or 0),
            race_distance_km=race_distance_km,
            race_elevation_m=race_elevation_m,
            race_type=race_type,
        )
        if polarized and phase == 'Build' and wt == 'intervals':
            day['title'] = ('VO2 intervals — 5x4min Z4-Z5, 3min easy jog '
                            '(uphill or treadmill incline if possible)')


# Treadmill days (coach-review: treadmill-only weekdays). A treadmill gives
# incline but no decline: climbing transfers, eccentric downhill load does not
# (Bontemps et al. 2020, Sports Med 50:2083 - downhill damage is blunted only
# by prior downhill/eccentric exposure, the repeated-bout effect). So
# descent_session must land on an outdoor day, and treadmill D+ is capped by
# the machine's max incline (10 % -> 100 m per km). Easy treadmill running at
# 1 % matches the energy cost of outdoor running above ~4 m/s
# (Jones & Doust 1996, J Sports Sci 14:321).
TREADMILL_DEFAULT_MAX_INCLINE_PCT = 10.0
_TREADMILL_NO_RUN = ('rest', 'strength')


def _move_descent_off_treadmill(placed: dict[str, str], treadmill: set[str],
                                mountain_set: set[str] | None, long_run_day: str) -> None:
    """Swap a descent_session placed on a treadmill day with an outdoor day.

    Prefers an outdoor climb-eligible day that is not the long run; with no
    outdoor slot the session becomes hill_repeats (uphill only) and the
    eccentric stimulus is left to strength work + the outdoor long run.
    """
    for d in DAYS_OF_WEEK:
        if placed[d] != 'descent_session' or d not in treadmill:
            continue
        outdoor = [o for o in DAYS_OF_WEEK
                   if o not in treadmill and o != long_run_day
                   and placed[o] not in ('rest', 'strength', 'long_run', 'race_simulation', 'easy_strides')
                   and (mountain_set is None or o in mountain_set)]
        if outdoor:
            o = outdoor[0]
            placed[d], placed[o] = placed[o], placed[d]
        else:
            placed[d] = 'hill_repeats'


# Minutes of sustained uphill per session and its speed: the machine gives exact
# grade, so a treadmill hill_repeats day is a climbing block, not 10 s sprints (#117).
TREADMILL_CLIMB_MIN = {'Base': 20, 'Build': 30, 'Peak': 45}
TREADMILL_CLIMB_KMH = 7.0


# Steady-climb floor (m D+ per km) for treadmill easy days when the race is
# mountainous (race D+/km >= TREADMILL_MOUNTAIN_DENSITY): ~2 % average grade.
TREADMILL_MOUNTAIN_DENSITY = 30.0
TREADMILL_EASY_CLIMB_M_PER_KM = 20.0


def _prefer_climb_on_treadmill(placed: dict[str, str], treadmill: set[str],
                               long_run_day: str) -> None:
    """Swap an outdoor hill_repeats/vert_session with a treadmill easy day (#117).

    Climbing transfers on a treadmill; outdoor days stay free for descent work.
    Only when neither day ends up adjacent to another hard session or the long run.
    """
    def clash(d: str, wt_by_day: dict[str, str]) -> bool:
        return any(wt_by_day[o] in HARD_WORKOUTS or o == long_run_day
                   for o in DAYS_OF_WEEK if o != d and _day_distance(d, o) == 1)

    for d in DAYS_OF_WEEK:
        if placed[d] not in ('hill_repeats', 'vert_session') or d in treadmill:
            continue
        for t in DAYS_OF_WEEK:
            if t in treadmill and placed[t] == 'easy':
                trial = dict(placed)
                trial[d], trial[t] = trial[t], trial[d]
                if not clash(t, trial) and not clash(d, trial):
                    placed[d], placed[t] = trial[d], trial[t]
                    break


def _apply_treadmill_limits(days: list[dict], treadmill: set[str], max_incline_pct: float,
                            phase: str = 'Build', mountain_race: bool = False) -> None:
    """Cap D+ to what the treadmill can give and tell the runner how to set it."""
    for day in days:
        if day['day'] not in treadmill or day['workout_type'] in _TREADMILL_NO_RUN:
            continue
        km = float(day.get('distance_km') or 0)
        cap = (km * max_incline_pct * 10) // 50 * 50  # m of climb at that grade, floored to the 50 m snap
        elev = float(day.get('elevation_m') or 0)
        if day['workout_type'] == 'hill_repeats':
            # D+ = minutes x km/h / 60 x incline% x 10 (m per km per %)
            elev = max(elev, TREADMILL_CLIMB_MIN.get(phase, 30) * TREADMILL_CLIMB_KMH / 60
                       * max_incline_pct * 10 // 50 * 50)
        elif mountain_race and day['workout_type'] == 'easy':
            elev = max(elev, km * TREADMILL_EASY_CLIMB_M_PER_KM)
        day['elevation_m'] = min(elev, round(cap))
        avg = day['elevation_m'] / (km * 10) if km else 0
        day['treadmill'] = True
        tag = (f"Treadmill: no decline. Climbs at up to {max_incline_pct:.0f}% "
               f"(avg ~{avg:.1f}% for the D+), easy parts at 1%.")
        day['notes'] = f"{tag} {day.get('notes') or ''}".strip()


def _fit_weekly_elev(days: list[dict], target_elev: float, treadmill: set[str],
                     phase: str) -> None:
    """Scale flexible outdoor days down when descent/hill sessions (sized outside
    the weekly D+ budget) push the week over target (#117)."""
    if phase == 'Race':
        return
    fixed = ('hill_repeats', 'vert_session', 'uphill_intervals', 'descent_session', 'long_run', 'race_simulation',
             'rest', 'strength', 'easy_strides')
    flex = [d for d in days if d['workout_type'] not in fixed and d['day'] not in treadmill]
    over = sum(float(d.get('elevation_m') or 0) for d in days) - target_elev
    pool = sum(float(d.get('elevation_m') or 0) for d in flex)
    if over > 0 and pool > 0:
        k = max(0.0, 1 - over / pool)
        for d in flex:
            d['elevation_m'] = float(d.get('elevation_m') or 0) * k


def _attach_strength_addon(days: list[dict], n: int, preferred: list[str] | None,
                           long_run_day: str) -> None:
    """Add strength to n easy/recovery run days (not next to the long run)."""
    ok = [d for d in days if d['workout_type'] in ('easy', 'recovery')]
    far = [d for d in ok if _day_distance(d['day'], long_run_day) > 1]
    pref = list(preferred or [])
    ranked = sorted(far or ok, key=lambda d: (d['day'] not in pref,
                                              d['workout_type'] != 'easy'))
    for d in ranked[:n]:
        d['strength'] = True
        d['notes'] = (f"{d.get('notes') or ''} + Strength & conditioning "
                      "(30 min, after the run).").strip()


# Daily readiness adjustments (RPE/sleep/feeling → swap today's quality with
# the easiest remaining day, or downgrade the next quality after two bad days
# in a row) are layered on top in ``services.plan_adjustment_service`` so the
# engine stays a pure deterministic function (coach-review #55).
def distribute_week(
    target: WeekTarget, phase: str, long_run_day: str, rest_days: list[str],
    training_ratio: float, back_to_back: bool, athlete_category: str,
    week_number: int,
    race_distance_km: float = 0, race_elevation_m: float = 0,
    mountain_days: list[str] | None = None,
    strength_days: int = 0, strength_preferred_days: list[str] | None = None,
    *,
    terrain_profile: str | None = None, mountain_budget: float | None = None,
    max_mountain_elevation_m: float | None = None,
    is_last_peak_week: bool = False,
    return_meta: bool = False,
    race_type: str = 'loop',
    treadmill_days: list[str] | None = None,
    treadmill_max_incline_pct: float = TREADMILL_DEFAULT_MAX_INCLINE_PCT,
    steep_descent: bool = False,
    intensity_distribution: str | None = None,
) -> list[dict] | tuple[list[dict], dict]:
    """Distribute weekly targets across 7 days.

    Pipeline:
      1. _place_fixed_slots: rest, strength, long-run / race-sim.
      2. _select_workouts_for_phase + _enforce_mountain_budget: pick types.
      3. _place_workouts: separation + mountain-day constraints.
      4. _size_distances + _size_elevations: budget distribution.
      5. _build_day_dicts: titles + caps.
      6. _redistribute_elevation: flatten low-density easy days.
    """
    polarized = intensity_distribution == 'polarized'
    mountain_set = set(mountain_days) if mountain_days is not None else None
    # Treadmill days can host climbing (incline) but never descent: they join
    # the climb-eligible set, and descent_session is moved off them below.
    treadmill_set = set(treadmill_days or [])
    if mountain_set is not None:
        mountain_set |= treadmill_set
    day_slots: dict[str, Optional[str]] = {d: None for d in DAYS_OF_WEEK}

    # Step 1a: rest days.
    for rd in rest_days:
        if rd in day_slots:
            day_slots[rd] = 'rest'

    # Strength is its own day slot only when the athlete has a rest day to
    # spare; a 7-day runner would otherwise lose a run, so there it becomes an
    # add-on to an easy/recovery day (``_attach_strength_addon``, coach-review #113).
    # Step 1b: strength sessions (avoid the LR day and its neighbours).
    # Race week: strength is dropped — the 5-day pre-race window must stay
    # neuromuscularly fresh (Mujika & Padilla, Magness, Hudson). Taper weeks
    # also skip strength because the catalog (PHASE_CATALOG['Taper']) has no
    # strength slot and the deload protects the freshness gain.
    strength_addons = 0
    if strength_days > 0 and phase not in ('Race', 'Taper') and not rest_days:
        strength_addons, strength_days = strength_days, 0
    if strength_days > 0 and phase not in ('Race', 'Taper'):
        candidates = list(strength_preferred_days or [])
        for d in DAYS_OF_WEEK:
            if d not in candidates:
                candidates.append(d)
        placed = 0
        for d in candidates:
            if placed >= strength_days:
                break
            if day_slots[d] is not None or d == long_run_day:
                continue
            if _day_distance(d, long_run_day) <= 1:
                continue
            day_slots[d] = 'strength'
            placed += 1

    # Step 1c: long_run / race_simulation on long_run_day.
    if phase == 'Race':
        day_slots[long_run_day] = 'race_simulation'
    elif phase == 'Peak' and is_last_peak_week:
        day_slots[long_run_day] = 'race_simulation'  # dress rehearsal
        # Pre-rehearsal day must be a shakeout — not a hard mountain workout.
        # Mujika & Padilla and Magness are explicit: a 60 km / 4200 m race-
        # effort rehearsal needs maximum freshness to deliver representative
        # pacing/HR data. Pinning ``easy_strides`` here makes the BTB pin in
        # _place_workouts skip this day (``prev`` is no longer in
        # training_days), so descent_session / vert_session can't land here.
        day_before_rehearsal = DAYS_OF_WEEK[(_day_offset(long_run_day) - 1) % 7]
        if day_slots[day_before_rehearsal] is None:
            day_slots[day_before_rehearsal] = 'easy_strides'
    else:
        day_slots[long_run_day] = 'long_run'

    # Step 1d: race-week pre-race shakeout.
    # Day-before-race must be the short ``easy_strides`` shakeout (4-6 km +
    # short pickups), not a generic 8-12 km easy run. Coaching consensus
    # (Magness, Hudson, Pfitzinger): the day before a race carries pre-race
    # nerves + strides to keep the legs sharp without fatigue. Pinning here
    # before training_days is computed so placement / sizing treat it as
    # fixed (it survives ``_drop_unfittable_easy_days`` because the shakeout
    # is intentionally short and always fits).
    if phase == 'Race':
        day_before = DAYS_OF_WEEK[(_day_offset(long_run_day) - 1) % 7]
        if day_slots[day_before] is None:
            day_slots[day_before] = 'easy_strides'

    training_days = [d for d in DAYS_OF_WEEK if day_slots[d] is None]

    # Step 2: workout selection + mountain-budget downgrade.
    # Last Peak week (dress rehearsal): suppress the descent_session
    # injection. With Sat pinned to easy_strides, only 3 mid-week training
    # days remain, and 2 mid-week hards cannot be placed without same-week
    # adjacency. Mujika & Padilla / Magness: the rehearsal IS the week's
    # central stimulus — mid-week stays light. Descent specificity is
    # already delivered by the prior Peak weeks' descent_sessions.
    inject_descent = (_wants_descent_session(phase, week_number, race_elevation_m, steep_descent)
                      and not is_last_peak_week)
    workouts = _select_workouts_for_phase(
        phase, len(training_days), athlete_category, week_number, back_to_back,
        inject_descent_session=inject_descent,
        race_type=race_type,
        polarized=polarized,
    )
    workouts = [w for w in workouts if w not in ('long_run', 'race_simulation')]
    workouts, mountain_orig, mountain_down = _enforce_mountain_budget(
        workouts, training_days, mountain_set, mountain_budget, week_number, phase,
        race_type=race_type,
    )
    # Dress-rehearsal week: collapse to at most 1 mid-week hard. Keep the
    # most race-specific (vert_session > hill_repeats > tempo > intervals);
    # the other slot becomes ``easy``. Without this, _select can still
    # return [vert_session, intervals] which forces same-week adjacency.
    if is_last_peak_week:
        # uphill_intervals ranks just below hill_repeats — for a VK dress
        # rehearsal it preserves climbing specificity, far closer to the
        # race demand than flat tempo / intervals (coach-review #44).
        hard_priority = {'vert_session': 0, 'hill_repeats': 1,
                         'uphill_intervals': 2, 'tempo': 3,
                         'intervals': 4, 'descent_session': 5}
        kept = False
        for i, w in enumerate(workouts):
            if w in HARD_WORKOUTS:
                if not kept and (i == min(
                    (j for j, x in enumerate(workouts) if x in HARD_WORKOUTS),
                    key=lambda j: hard_priority.get(workouts[j], 9),
                )):
                    kept = True
                else:
                    workouts[i] = 'easy'
    while len(workouts) < len(training_days):
        workouts.append('easy')
    workouts = workouts[:len(training_days)]

    # Step 3: placement.
    day_slots = _place_workouts(
        workouts, list(training_days), day_slots,
        long_run_day, mountain_set, back_to_back, phase,
    )
    placed: dict[str, str] = {d: day_slots[d] for d in DAYS_OF_WEEK}  # type: ignore[misc]
    if treadmill_set:
        _move_descent_off_treadmill(placed, treadmill_set, mountain_set, long_run_day)
        _prefer_climb_on_treadmill(placed, treadmill_set, long_run_day)

    # Step 4: sizing.
    long_run_is_mountain = (mountain_set is None or long_run_day in mountain_set)
    long_run_km = target.long_run_km
    long_run_elev = (target.long_run_elev if long_run_is_mountain
                     else long_run_km * FLAT_CITY_ELEV_DENSITY)

    if phase == 'Race':
        race_sim_km, race_sim_elev = race_distance_km, race_elevation_m
    elif phase == 'Peak' and is_last_peak_week:
        # Quality fix: the last Peak race-simulation must NOT be empty.
        # Conventional dress rehearsal is ~60 % of race distance at race
        # effort + proportional D+. Honors the per-outing mountain cap.
        race_sim_km = race_distance_km * PEAK_DRESS_REHEARSAL_FRACTION
        race_sim_elev = race_elevation_m * PEAK_DRESS_REHEARSAL_FRACTION
        if max_mountain_elevation_m is not None:
            race_sim_elev = min(race_sim_elev, max_mountain_elevation_m)
        # On flat_urban runners, the rehearsal is on a flat day.
        if not long_run_is_mountain:
            race_sim_elev = race_sim_km * FLAT_CITY_ELEV_DENSITY
    else:
        race_sim_km, race_sim_elev = 0.0, 0.0

    # ``easy_strides`` pre-pinned for race week or the dress-rehearsal week
    # is a deterministic 4 km / 0 m shakeout (sized in ``_build_day_dicts``).
    # Treat it as fixed so ``_drop_unfittable_easy_days`` can't demolish it
    # when the budget is tight — losing the shakeout silently breaks the
    # pre-rehearsal freshness fix (issue #36) and the race-week pre-race
    # pin handled below.
    fixed_types: tuple[str, ...] = ('long_run', 'race_simulation', 'rest', 'strength')
    if phase == 'Race' or (phase == 'Peak' and is_last_peak_week):
        fixed_types = fixed_types + ('easy_strides',)
    non_fixed = [d for d in DAYS_OF_WEEK if placed[d] not in fixed_types]
    fixed_shakeout_km = sum(
        4.0 for d in DAYS_OF_WEEK if placed[d] == 'easy_strides'
        and (phase == 'Race' or (phase == 'Peak' and is_last_peak_week))
    )

    weekly_fixed_km = (race_sim_km if phase == 'Race'
                       else (long_run_km + (race_sim_km if is_last_peak_week else 0)))
    weekly_fixed_km += fixed_shakeout_km
    weekly_fixed_elev = (race_sim_elev if phase == 'Race'
                         else (long_run_elev + (race_sim_elev if is_last_peak_week else 0)))

    remaining_km = max(0, target.weekly_km - weekly_fixed_km)
    remaining_elev = max(0, target.weekly_elev - weekly_fixed_elev)

    # When the budget is too tight to give each non-fixed day its
    # coaching minimum (easy ≥ 6 km etc.), drop easy/recovery slots to
    # rest before sizing. This is the "max_weekly_km" path.
    non_fixed = _drop_unfittable_easy_days(placed, non_fixed, remaining_km, phase)

    distances = _size_distances(non_fixed, placed, remaining_km, phase)
    elevations = _size_elevations(
        non_fixed, placed, distances,
        training_ratio=training_ratio, remaining_elev=remaining_elev,
        mountain_set=mountain_set,
        phase=phase,
        terrain_profile=terrain_profile,
    )

    # Step 5: materialize.
    midweek_cap = MIDWEEK_ELEV_CAP.get(terrain_profile) if terrain_profile else None
    days = _build_day_dicts(
        placed,
        long_run_km=long_run_km, long_run_elev=long_run_elev,
        long_run_is_mountain=long_run_is_mountain,
        race_sim_km=race_sim_km, race_sim_elev=race_sim_elev,
        distances=distances, elevations=elevations,
        phase=phase, training_ratio=training_ratio,
        midweek_cap=midweek_cap,
        max_mountain_elevation_m=max_mountain_elevation_m,
        race_distance_km=race_distance_km, race_elevation_m=race_elevation_m,
        race_type=race_type,
        treadmill_set=treadmill_set,
    )

    # Step 6: flatten low-density easy days, redistribute saved D+.
    days, residual, planned_total = _redistribute_elevation(
        days, phase, terrain_profile=terrain_profile,
    )
    # Re-apply caps: redistribution can push sink days past midweek /
    # mountain-outing limits. Idempotent and cheap.
    _reapply_elev_caps(
        days, midweek_cap=midweek_cap,
        max_mountain_elevation_m=max_mountain_elevation_m,
        treadmill_set=treadmill_set,
    )
    # Step 7: break runs of >2 consecutive rest days. Catches the Race-week
    # Mon–Fri all-rest pattern and Taper weeks where the budget collapses
    # multiple easy days into rest via _drop_unfittable_easy_days.
    _enforce_max_consecutive_rest(
        days, phase, rest_days,
        race_distance_km=race_distance_km,
        race_elevation_m=race_elevation_m,
        race_type=race_type,
    )
    # Re-apply caps in case the inserted shakeout's elevation exceeds the
    # midweek / flat-urban limits.
    _reapply_elev_caps(
        days, midweek_cap=midweek_cap,
        max_mountain_elevation_m=max_mountain_elevation_m,
        treadmill_set=treadmill_set,
    )
    # Step 8: race-distance regime cap for back-to-back weekends. A 50K
    # plan should not ship a 50+km / 3000+m Sat+Sun stack — that's 100K
    # specificity, not 50K. Applied AFTER caps & redistribution because it
    # is the final word on weekend sizing.
    _apply_regime_weekend_cap(
        days, long_run_day, phase,
        race_distance_km=race_distance_km, race_elevation_m=race_elevation_m,
        race_type=race_type,
    )
    if treadmill_set:
        _apply_treadmill_limits(
            days, treadmill_set, treadmill_max_incline_pct, phase,
            mountain_race=(race_distance_km > 0
                           and race_elevation_m / race_distance_km >= TREADMILL_MOUNTAIN_DENSITY))
    _fit_weekly_elev(days, target.weekly_elev, treadmill_set, phase)
    if strength_addons:
        _attach_strength_addon(days, strength_addons, strength_preferred_days, long_run_day)
    # Step 9: snap to coaching granularity (50 m D+) and refresh titles.
    _round_and_refresh_titles(
        days, phase,
        race_distance_km=race_distance_km, race_elevation_m=race_elevation_m,
        race_type=race_type, polarized=polarized,
    )

    meta = {
        'original_mountain_count': mountain_orig,
        'mountain_downgraded': mountain_down,
        'elev_residual_m': residual,
        'elev_planned_total_m': planned_total,
    }
    if return_meta:
        return days, meta
    return days


# =========================================================================
# Layer 4: Race profile customization (titles / notes only)
# =========================================================================

def apply_key_sections(weeks: list[dict], key_sections: list[dict] | None) -> None:
    """Customize workout titles and notes based on race key sections."""
    if not key_sections:
        return

    climbs = [s for s in key_sections if s.get('type') in ('steep_climb', 'long_climb')]
    has_descents = any(s.get('type') == 'steep_descent' for s in key_sections)
    steepest = max(climbs, key=lambda s: abs(s.get('avg_grade_pct', 0))) if climbs else None
    longest = max(climbs, key=lambda s: s.get('distance_km', 0)) if climbs else None

    for week in weeks:
        # If the engine already injected a structured descent_session this
        # week, the legacy note ("Include controlled descent practice") is
        # redundant noise — suppress it.
        descent_done = any(d['workout_type'] == 'descent_session'
                           for d in week['days'])
        for day in week['days']:
            wt = day['workout_type']
            if wt == 'hill_repeats' and steepest:
                # Keep the profile title (reps x duration match the
                # deterministic HILL_REPEATS_PROFILE load); the race climb is
                # only the target effort (coach-review #111).
                km_start = steepest.get('km_start', 0)
                day['title'] = (f"{day['title']} — effort of race km "
                                f"{km_start:.0f} climb")
            if wt == 'vert_session' and longest:
                km_start = longest.get('km_start', 0)
                km_end = longest.get('km_end', km_start)
                day['title'] = (f"Sustained Z3 climbing — simulating race "
                                f"km {km_start:.0f}-{km_end:.0f}")
            if (wt == 'easy' and has_descents and not descent_done
                    and not day['notes']):
                day['notes'] = 'Include controlled descent practice'
                descent_done = True


# =========================================================================
# Calendar dates
# =========================================================================

def compute_calendar(total_weeks: int, race_date_str: str):
    """Return [(monday_date, [mon..sun]), ...] anchored at the race week."""
    race_dt = datetime.strptime(race_date_str, '%Y-%m-%d').date()
    race_week_monday = race_dt - timedelta(days=race_dt.weekday())
    week1_monday = race_week_monday - timedelta(weeks=total_weeks - 1)
    return [
        (week1_monday + timedelta(weeks=w),
         [week1_monday + timedelta(weeks=w, days=i) for i in range(7)])
        for w in range(total_weeks)
    ]


def _phase_theme(phase: str) -> str:
    """Generate a descriptive theme string for a phase."""
    return {
        'Base': 'Base — aerobic foundation',
        'Build': 'Build — increasing specificity',
        'Peak': 'Peak — race-specific intensity',
        'Recovery': 'Recovery — adaptation & rest',
        'Taper': 'Taper — sharpening',
        'Race': 'Race week',
    }.get(phase, phase)


# =========================================================================
# Main entry point
# =========================================================================

def _mountain_budget_per_week(prefs: dict | None) -> float | None:
    """Weekly mountain workout budget (per_week → per_month/4.33 → mountain_days → None)."""
    if not prefs:
        return None
    if prefs.get('mountain_access_per_week') is not None:
        return float(prefs['mountain_access_per_week'])
    if prefs.get('mountain_access_per_month') is not None:
        return float(prefs['mountain_access_per_month']) / 4.33
    md = prefs.get('mountain_days') or []
    if md:
        return float(len(md))
    return None


def _training_ratio_for(race_type: str, race_distance_km: float, race_elevation_m: float) -> float:
    if race_distance_km <= 0:
        return 0.0
    if race_type == 'uphill_only':
        return race_elevation_m / (race_distance_km * 2)
    return race_elevation_m / race_distance_km


# TODO(coach-review #4 — see GH issues): one-shot generation, no in-flight recalibration.
# generate_plan() is called once at plan creation. There is no service that
# re-evaluates the remaining weeks from current compliance/TSB/race-result deltas
# (issues #55, #58, #64). Add plan_adjustment_service.reevaluate_plan(plan_id, anchor_week).
# TODO(coach-review #9 — see GH issues): no auto tune-up race scaffolding.
# When the target is a 100K/100M, best practice schedules a 50K race ~6-8w out and
# optionally a 10-21K ~3-4w out. We don't propose them — only validate user-entered
# races in season_planning_service. Inject suggested races + treat the week as
# "race-as-long-run" (skip planned LR, 2-3d taper before, 2-3d recovery after).
# TODO(coach-review #10 — see GH issues): no recalibration from intermediate race results.
# After a B-race, observed-vs-predicted delta should damped-Bayesian-update v_flat
# in UserLearnedParams and re-run the engine on remaining weeks. Today the result
# is stored in race_results and ignored by future weeks.
def generate_plan(
    total_weeks: int,
    race_distance_km: float,
    race_elevation_m: float,
    race_date: str,
    athlete_weekly_km: float,
    athlete_weekly_elev: float,
    athlete_longest_run_km: float,
    athlete_category: str,
    long_run_day: str,
    rest_days: list[str],
    race_type: str = 'loop',
    training_ratio: float | None = None,
    key_sections: list[dict] | None = None,
    back_to_back: bool | None = None,
    overrides: dict | None = None,
    mountain_days: list[str] | None = None,
    # ``strength_days`` defaults to 0 to preserve back-compat for short / flat
    # plans, but mountain ultras silently auto-default to 1 (Tuesday) inside
    # the body — see the ``_should_default_strength`` block below. Magness /
    # Koop / Roche / Vert.run all classify strength as non-negotiable for
    # races ≥ 50 km / 1500 m D+.
    strength_days: int = 0,
    strength_preferred_days: list[str] | None = None,
    *,
    prefs: dict | None = None,
    terrain_profile: str | None = None,
    athlete_flat_pace_min_km: float | None = None,
    treadmill_days: list[str] | None = None,
    treadmill_max_incline_pct: float | None = None,
    intensity_distribution: str | None = None,
) -> list[dict]:
    """Generate a complete training plan.

    Returns a list of week dicts: ``{week_number, theme, total_km,
    total_elevation_m, start_date, days: [...], valid: True, _meta}``.
    """
    T = _resolve_tunables(overrides)

    prefs_dict = prefs or {}
    if terrain_profile is None:
        terrain_profile = prefs_dict.get('terrain_profile')
    if mountain_days is None and prefs_dict.get('mountain_days'):
        mountain_days = list(prefs_dict['mountain_days']) or None
    if treadmill_days is None:
        treadmill_days = prefs_dict.get('treadmill_days') or None
    if treadmill_max_incline_pct is None:
        treadmill_max_incline_pct = prefs_dict.get('treadmill_max_incline_pct')

    if intensity_distribution is None:
        intensity_distribution = prefs_dict.get('intensity_distribution')
    if intensity_distribution not in INTENSITY_DISTRIBUTIONS:
        intensity_distribution = None

    mountain_budget = _mountain_budget_per_week(prefs_dict)
    max_weekly_km = prefs_dict.get('max_weekly_km')
    max_long_run_km = prefs_dict.get('max_long_run_km')
    max_long_run_hours = prefs_dict.get('max_long_run_hours')
    max_mountain_elevation_m = prefs_dict.get('max_mountain_elevation_m')
    available_hours_per_week = prefs_dict.get('available_hours_per_week')
    long_long_run_hours = prefs_dict.get('long_long_run_hours')
    long_long_run_every_weeks = prefs_dict.get('long_long_run_every_weeks')

    if training_ratio is None:
        training_ratio = _training_ratio_for(race_type, race_distance_km, race_elevation_m)

    # Default back-to-back ON for ultra distances (>= 50 km). Coaching
    # consensus (Koop "Training Essentials for Ultrarunning", Roche, Magness)
    # makes consecutive long-day weekends the central specificity stimulus
    # for ultras: simulates fatigued running without the recovery cost of a
    # single mega-long run. Caller can still opt out by passing
    # ``back_to_back=False`` explicitly.
    #
    # Also default BTB ON for VK / uphill_only races. Without it, the engine
    # enforces a 2-day separation between the long_run (Sun) and any hard
    # session, which makes the only mountain weekend day (Sat) ineligible for
    # hill_repeats / vert_session — the placer silently drops the climbing
    # session to ``easy``. The Sat-hill + Sun-long-mountain sandwich is the
    # canonical VK weekend stack (Vert.run, Suunto, Lavedrine 2024). Override
    # by passing ``back_to_back=False`` explicitly.
    if back_to_back is None:
        back_to_back = (race_distance_km >= 50.0 or race_type == 'uphill_only')

    # Coaching default: ultra-mountain plans get 1 strength session/week.
    # Magness, Koop, Roche, Vert.run all classify strength as non-negotiable
    # for races ≥ 50 km / 1500 m D+ — eccentric quad / glute-med / calf work
    # is the #1 limiter on long descents. The user opts out explicitly via
    # prefs={'strength_opt_out': True}; otherwise a silent 0 → 1 default is
    # safer than silently shipping no strength on a 100K mountain plan.
    #
    # VK / uphill_only races also auto-default to 1 strength/week regardless
    # of distance: Vert.run, Suunto and Lavedrine 2024 all prescribe a weekly
    # leg-strength routine (squats, lunges, calf raises, eccentric step-downs)
    # for short uphill races. Muscular endurance of glutes/quads/calves is
    # the rate-limiter at 20 %+ average grades — same physiology as ultra
    # descents but on the concentric / isometric side.
    is_ultra_mountain = (race_distance_km >= ULTRA_DISTANCE_THRESHOLD_KM
                         and race_elevation_m >= DESCENT_TRAINING_ELEV_THRESHOLD)
    is_short_uphill = race_type == 'uphill_only'
    if (strength_days == 0
            and not prefs_dict.get('strength_opt_out')
            and terrain_profile in ('rolling_hills', 'mountain')
            and (is_ultra_mountain or is_short_uphill)):
        strength_days = 1
        if not strength_preferred_days:
            strength_preferred_days = ['Tuesday']

    # Layer 1: phases.
    phases = assign_phases(total_weeks, athlete_category)

    # Layer 2: weekly targets.
    targets = compute_weekly_targets(
        phases=phases,
        athlete_weekly_km=athlete_weekly_km,
        athlete_weekly_elev=athlete_weekly_elev,
        athlete_longest_run_km=athlete_longest_run_km,
        race_distance_km=race_distance_km,
        race_elevation_m=race_elevation_m,
        training_ratio=training_ratio,
        tunables=T,
        race_type=race_type,
        max_weekly_km=max_weekly_km,
        max_long_run_km=max_long_run_km,
        max_long_run_hours=max_long_run_hours,
        athlete_flat_pace_min_km=athlete_flat_pace_min_km,
        available_hours_per_week=available_hours_per_week,
        long_long_run_hours=long_long_run_hours,
        long_long_run_every_weeks=(int(long_long_run_every_weeks)
                                  if long_long_run_every_weeks else None),
    )

    calendar = compute_calendar(total_weeks, race_date)

    steep_descent = any(s.get('type') == 'steep_descent' for s in key_sections or [])
    last_peak_idx = max((i for i, p in enumerate(phases) if p == 'Peak'), default=-1)

    # Layer 3: daily distribution.
    weeks: list[dict] = []
    for i, (target, (week_monday, daily_dates)) in enumerate(zip(targets, calendar)):
        days, week_meta = distribute_week(
            target=target, phase=target.phase,
            long_run_day=long_run_day, rest_days=rest_days,
            training_ratio=training_ratio, back_to_back=back_to_back,
            athlete_category=athlete_category, week_number=target.week_number,
            race_distance_km=race_distance_km, race_elevation_m=race_elevation_m,
            mountain_days=mountain_days,
            strength_days=strength_days, strength_preferred_days=strength_preferred_days,
            terrain_profile=terrain_profile, mountain_budget=mountain_budget,
            max_mountain_elevation_m=max_mountain_elevation_m,
            is_last_peak_week=(i == last_peak_idx),
            return_meta=True,
            race_type=race_type,
            treadmill_days=treadmill_days,
            treadmill_max_incline_pct=treadmill_max_incline_pct or TREADMILL_DEFAULT_MAX_INCLINE_PCT,
            steep_descent=steep_descent,
            intensity_distribution=intensity_distribution,
        )

        for day_dict, day_date in zip(days, daily_dates):
            day_dict['date'] = day_date.strftime('%Y-%m-%d')

        weeks.append({
            'week_number': target.week_number,
            'theme': _phase_theme(target.phase),
            'total_km': round(sum(d['distance_km'] for d in days), 1),
            'total_elevation_m': round(sum(d['elevation_m'] for d in days), 0),
            'start_date': week_monday.strftime('%Y-%m-%d'),
            'days': days,
            'valid': True,
            '_meta': week_meta,
        })

    # Layer 4: race-specific titles / notes.
    apply_key_sections(weeks, key_sections)

    return weeks


# =========================================================================
# Feasibility validation
# =========================================================================

def _summarize_meta(plan_weeks: list[dict]) -> tuple[int, int, float, float]:
    """Aggregate the per-week _meta telemetry across the plan."""
    mtn_planned = mtn_down = 0
    elev_residual = elev_planned = 0.0
    for w in plan_weeks or []:
        meta = (w.get('_meta') or {}) if isinstance(w, dict) else {}
        mtn_planned += int(meta.get('original_mountain_count') or 0)
        mtn_down += int(meta.get('mountain_downgraded') or 0)
        elev_residual += float(meta.get('elev_residual_m') or 0)
        elev_planned += float(meta.get('elev_planned_total_m') or 0)
    return mtn_planned, mtn_down, elev_residual, elev_planned


def _race_terrain_warning(
    terrain_profile: str | None,
    race_distance_km: float | None, race_elevation_m: float | None,
) -> dict | None:
    if not (terrain_profile == 'flat_urban' and race_distance_km
            and race_elevation_m and race_distance_km > 0):
        return None
    density = race_elevation_m / race_distance_km
    if density <= 30:
        return None
    return {
        'severity': 'critical', 'week': None, 'day': None,
        'issue': 'race_terrain_mismatch',
        'target': f"{density:.0f} m/km gara",
        'cap': "profilo utente: flat_urban (~5 m/km)",
        'suggestion': (
            "L'ambiente di allenamento non riesce a riprodurre le richieste di gara. "
            "Considera: (a) viaggi in montagna nei weekend chiave, "
            "(b) treadmill con pendenza per simulazione vert, "
            "(c) revisione obiettivo gara."
        ),
    }


def _import_time_budget():
    """Lazy import for predict_time_for_distance helpers (kept optional)."""
    try:
        from services.physics_model.time_budget import (
            effort_for_workout, predict_time_for_distance,
        )
        return effort_for_workout, predict_time_for_distance
    except Exception:  # pragma: no cover - optional dep
        return None, None


def _check_week_volume(
    week: dict, prev_km: float | None, max_weekly_km: float | None,
) -> list[dict]:
    out: list[dict] = []
    weekly_km = float(week.get('total_km') or 0)
    wk_no = week.get('week_number') or 0
    if max_weekly_km is not None and weekly_km > max_weekly_km + 0.5:
        out.append({
            'severity': 'warning', 'week': wk_no, 'day': None,
            'issue': 'volume_above_cap',
            'target': round(weekly_km, 1), 'cap': max_weekly_km,
            'suggestion': ("La settimana supera il massimo dichiarato. "
                           "Riduci alcuni workout easy o sposta volume sul long run successivo."),
        })
    if prev_km and weekly_km > prev_km * MAX_WEEKLY_INCREASE + 0.5:
        out.append({
            'severity': 'warning', 'week': wk_no, 'day': None,
            'issue': 'volume_jump',
            'target': round(weekly_km, 1),
            'cap': round(prev_km * MAX_WEEKLY_INCREASE, 1),
            'suggestion': "Salto di volume >10% rispetto alla settimana precedente.",
        })
    return out


def _check_week_hours(
    week: dict, available_hours: float | None,
    effort_for_workout, predict_time_for_distance,
) -> list[dict]:
    if not (available_hours and predict_time_for_distance and effort_for_workout):
        return []
    total = sum(
        predict_time_for_distance(
            float(d.get('distance_km') or 0),
            float(d.get('elevation_m') or 0),
            learned_params=None, effort=effort_for_workout(d.get('workout_type') or 'easy'),
        )
        for d in week.get('days', [])
    )
    if total <= float(available_hours) * 1.10:
        return []
    return [{
        'severity': 'warning', 'week': week.get('week_number') or 0, 'day': None,
        'issue': 'weekly_hours_above_cap', 'code': 'weekly_hours_above_cap',
        'target': round(total, 1), 'cap': round(float(available_hours), 1),
        'suggestion': (f"Settimana stimata in {total:.1f}h "
                       f"contro un budget di {float(available_hours):.1f}h. "
                       "Riduci durata o numero di sessioni."),
    }]


def _check_day(
    day: dict, week_no: int, prefs: dict,
    midweek_cap: float | None,
    predict_time_for_distance,
) -> list[dict]:
    out: list[dict] = []
    wt = day.get('workout_type')
    day_name = day.get('day')
    km = float(day.get('distance_km') or 0)
    elev = float(day.get('elevation_m') or 0)

    max_long_run_km = prefs.get('max_long_run_km')
    max_long_run_hours = prefs.get('max_long_run_hours')
    max_mountain_elev = prefs.get('max_mountain_elevation_m')

    if (wt == 'long_run' and max_long_run_hours and predict_time_for_distance):
        est_h = predict_time_for_distance(km, elev, learned_params=None, effort='long_run')
        # Long-long weeks may reach long_long_run_hours (ponytail: any long run
        # is checked against it, not only the scheduled long-long weeks).
        cap_h = float(max_long_run_hours)
        if prefs.get('long_long_run_every_weeks'):
            cap_h = max(cap_h, float(prefs.get('long_long_run_hours') or 0))
        if est_h > cap_h * 1.10:
            out.append({
                'severity': 'warning', 'week': week_no, 'day': day_name,
                'issue': 'long_run_hours_above_cap', 'code': 'long_run_hours_above_cap',
                'target': round(est_h, 1), 'cap': round(float(max_long_run_hours), 1),
                'suggestion': "Il lungo stimato supera il tuo tempo massimo dichiarato.",
            })

    if (wt == 'long_run' and max_long_run_km is not None
            and km > max_long_run_km + 0.5):
        out.append({
            'severity': 'warning', 'week': week_no, 'day': day_name,
            'issue': 'long_run_above_cap',
            'target': round(km, 1), 'cap': max_long_run_km,
            'suggestion': "Il long run supera il massimo dichiarato.",
        })

    if (midweek_cap is not None and day_name in MIDWEEK_DAYS
            and wt not in ('long_run', 'race_simulation', 'rest', 'strength')
            and not (wt in MIDWEEK_CAP_EXEMPT and midweek_cap > MIDWEEK_ELEV_CAP['flat_urban'])
            and not day.get('treadmill')
            and elev > midweek_cap + 0.5):
        out.append({
            'severity': 'warning', 'week': week_no, 'day': day_name,
            'issue': 'midweek_elev_too_high',
            'target': round(elev), 'cap': midweek_cap,
            'suggestion': ("Workout infrasettimanale con D+ superiore al terreno disponibile. "
                           "Riduci il dislivello o spostalo nel weekend."),
        })

    if (wt in MOUNTAIN_WORKOUTS and max_mountain_elev is not None
            and elev > max_mountain_elev + 0.5):
        out.append({
            'severity': 'warning', 'week': week_no, 'day': day_name,
            'issue': 'mountain_elev_above_cap',
            'target': round(elev), 'cap': max_mountain_elev,
            'suggestion': "Uscita mountain oltre il D+ raggiungibile dichiarato.",
        })

    if day.get('route_match_quality') == 'unmatched':
        out.append({
            'severity': 'info', 'week': week_no, 'day': day_name,
            'issue': 'unmatched_route',
            'target': {'km': km, 'elev': elev, 'workout_type': wt},
            'cap': None,
            'suggestion': ("Nessun percorso utente compatibile. "
                           "Genera con ORS, carica un GPX o riduci il target."),
        })
    return out


def validate_plan_feasibility(
    plan_weeks: list[dict],
    prefs: dict | None,
    terrain_profile: str | None,
    *,
    race_distance_km: float | None = None,
    race_elevation_m: float | None = None,
) -> list[dict]:
    """Compare a generated plan against the user's declared capacity.

    Returns a list of warning dicts (severity, week, day, issue, target,
    cap, suggestion). Empty list = no concerns.
    """
    warnings: list[dict] = []
    prefs = prefs or {}

    midweek_cap = MIDWEEK_ELEV_CAP.get(terrain_profile) if terrain_profile else None
    mountain_budget = _mountain_budget_per_week(prefs)

    # Plan-level: race terrain mismatch.
    rt_warn = _race_terrain_warning(terrain_profile, race_distance_km, race_elevation_m)
    if rt_warn:
        warnings.append(rt_warn)

    # Plan-level: aggregate mountain-downgrade telemetry.
    mtn_planned, mtn_down, elev_residual, elev_planned = _summarize_meta(plan_weeks)

    if mtn_planned > 0:
        ratio = mtn_down / mtn_planned
        if ratio > 0.30:
            warnings.append({
                'severity': 'warning', 'week': None, 'day': None,
                'issue': 'mountain_specificity_lost', 'code': 'mountain_specificity_lost',
                'target': mtn_down, 'cap': mtn_planned,
                'suggestion': (
                    f"{mtn_down} mountain-specific workouts were downgraded to "
                    f"flat sessions because of your mountain access budget — "
                    f"that's {ratio:.0%} of the originally prescribed mountain "
                    f"work. Consider raising mountain_access_per_week if your "
                    f"race has significant elevation."
                ),
            })

    if elev_planned > 0 and elev_residual / elev_planned > 0.15:
        warnings.append({
            'severity': 'info', 'week': None, 'day': None,
            'issue': 'weekly_elev_below_target', 'code': 'weekly_elev_below_target',
            'target': round(elev_residual), 'cap': round(elev_planned),
            'suggestion': ("Weekly elevation target couldn't be fully met: "
                           "climb-focused days hit the elevation density cap. "
                           "Consider raising max_mountain_distance_km or adding "
                           "a vert_session."),
        })

    # Plan-level: ultra-distance peak LR specificity check.
    if race_distance_km and race_distance_km >= ULTRA_DISTANCE_THRESHOLD_KM:
        peak_lr_km = 0.0
        for w in plan_weeks or []:
            theme = (w.get('theme') or '')
            if theme.startswith(('Recovery', 'Taper', 'Race')):
                continue
            for day in w.get('days', []):
                if day.get('workout_type') in ('long_run', 'race_simulation'):
                    peak_lr_km = max(peak_lr_km, float(day.get('distance_km') or 0))
        min_required = race_distance_km * ULTRA_PEAK_LR_MIN_FRACTION
        if 0 < peak_lr_km < min_required:
            warnings.append({
                'severity': 'warning', 'week': None, 'day': None,
                'issue': 'peak_lr_below_ultra_target',
                'code': 'peak_lr_below_ultra_target',
                'target': round(peak_lr_km, 1),
                'cap': round(min_required, 1),
                'suggestion': (
                    f"Il long run di picco ({peak_lr_km:.0f} km) è sotto il "
                    f"~50% della distanza gara ({race_distance_km:.0f} km). "
                    "Il piano non prepara completamente alla fatica tardo-gara "
                    "tipica di un ultra: aumenta available_hours_per_week o "
                    "max_long_run_hours per consentire un picco più vicino a "
                    f"{min_required:.0f} km."
                ),
            })

    effort_for, predict_time = _import_time_budget()

    max_weekly_km = prefs.get('max_weekly_km')
    available_hours = prefs.get('available_hours_per_week')

    # Baseline for the volume_jump check skips Recovery / Taper / Race weeks
    # — those are intentional deloads and mirror the same skip the engine
    # applies in compute_weekly_targets when enforcing MAX_WEEKLY_INCREASE.
    # Comparing a Build to the previous Recovery week always trips the 10 %
    # rule and produces false positives. Themes that are not explicitly a
    # deload phase (incl. tests using ``theme='Test'``) keep the previous
    # week's volume as baseline so legitimate jumps still warn.
    prev_km: float | None = None
    for week in plan_weeks or []:
        theme = (week.get('theme') or '')
        # Race-week total_km includes the race itself, so the volume_jump
        # check would always trip against the previous Peak. Skip the
        # progression check entirely on race week — only the absolute
        # volume_above_cap check still applies.
        is_race_week = theme.startswith('Race')
        warnings.extend(_check_week_volume(
            week, None if is_race_week else prev_km, max_weekly_km,
        ))
        warnings.extend(_check_week_hours(
            week, available_hours, effort_for, predict_time,
        ))

        wk_no = week.get('week_number') or 0
        mountain_count = 0
        for day in week.get('days', []):
            warnings.extend(_check_day(day, wk_no, prefs, midweek_cap, predict_time))
            if day.get('workout_type') in MOUNTAIN_WORKOUTS:
                mountain_count += 1

        if (mountain_budget is not None
                and mountain_count > max(1, int(round(mountain_budget))) + 0.5
                and not (mountain_budget < 1 and mountain_count == 1)):
            warnings.append({
                'severity': 'warning', 'week': wk_no, 'day': None,
                'issue': 'mountain_budget_exceeded',
                'target': mountain_count, 'cap': mountain_budget,
                'suggestion': ("Numero di uscite mountain in eccesso rispetto "
                               "alla disponibilità."),
            })

        # Use the current week as baseline for the next iteration only when
        # it represents a real training load. Recovery / Taper / Race weeks
        # are intentional deloads — the next progression week jumping
        # against them would falsely trip the 10 % rule.
        is_deload = theme.startswith(('Recovery', 'Taper', 'Race'))
        if not is_deload:
            prev_km = float(week.get('total_km') or 0)

    return warnings


# =========================================================================
# Self-test
# =========================================================================

if __name__ == '__main__':
    plan = generate_plan(
        total_weeks=7, race_distance_km=50, race_elevation_m=3500,
        race_date='2026-05-10',
        athlete_weekly_km=55, athlete_weekly_elev=2100,
        athlete_longest_run_km=25, athlete_category='cat_1',
        long_run_day='Sunday', rest_days=['Friday'],
        prefs={'max_weekly_km': 80, 'terrain_profile': 'mountain'},
    )
    for week in plan:
        print(
            f"\nW{week['week_number']} [{week['theme']}] "
            f"{week['total_km']:.0f}km / {week['total_elevation_m']:.0f}m D+ "
            f"(start: {week['start_date']})"
        )
        for d in week['days']:
            print(
                f"  {d['day'][:3]} {d['date']}: "
                f"{d['workout_type']:15s} {d['distance_km']:5.1f}km / "
                f"{d['elevation_m']:5.0f}m D+ | {d['title']}"
            )

"""Which of a user's activities look like races (pred-review #96, #101).

A score in [0, 1] with the reasons behind it, from signals known after the
fact: the name, a race in our calendar (or the user's own planned race) on the
same day and place/distance, an effort well above the user's usual for that
distance, and a weekend-morning start. Nothing is marked automatically: only
Strava's own flag or the user's confirmation sets `Activity.is_race`.
"""

import re
import statistics
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import defer

from database import db
from models import Activity, Race, TrainingPlan
from services.race_calendar_service import _haversine_km

CANDIDATE_MIN_SCORE = 0.4
LOOKBACK_DAYS = 730
RUN_TYPES = ('run', 'trail_run')

# Word-boundary keywords, accents stripped, it/en/fr/es.
STRONG = re.compile(
    r'\b(gara|race|ultra\w*|sky ?race|sky ?marathon|marathon|maratona|maratonina|mezza|half|semi|'
    r'carrera|maraton|utmb|ccc|occ|tds|mcc|pettorale|bib|dossard|dorsal|trofeo|campionato|'
    r'championship|championnat|competizione)\b')
WEAK = re.compile(r'\b(trail|ecotrail|20\d\d)\b')
# Watch/app default names say "trail" without meaning anything.
DEFAULT_NAME = re.compile(
    r'^((morning|lunch|afternoon|evening|night) (trail )?run|'
    r'(sessione di )?(trail running|corsa)( \w+)?|'
    r'(corsa|trail) (mattutina|pomeridiana|serale|notturna|all\'ora di pranzo))$')

CALENDAR_PLACE_KM = 20
PLANNED_WEIGHT, CALENDAR_WEIGHT = 0.6, 0.45
STRONG_WEIGHT, WEAK_WEIGHT = 0.5, 0.15
EFFORT_STRONG, EFFORT_MILD = 0.90, 0.95   # normalised pace vs the user's median
WEEKEND_WEIGHT = 0.1


def _plain(name: str) -> str:
    s = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', s).strip()


def _effort_km(a) -> float:
    return a.distance / 1000 + (a.elevation_gain_m or 0) / 100


def _norm_pace(a) -> Optional[float]:
    """km-effort pace with Riegel's distance exponent taken out (s per km-effort)."""
    ekm = _effort_km(a)
    if not a.moving_time_s or ekm < 1:
        return None
    return a.moving_time_s / ekm / ekm ** 0.06


def _same_distance(km: float, race_km: float) -> bool:
    return abs(km - race_km) <= max(2.0, 0.12 * race_km)


def score_activity(a, history: List, races: List[Race], planned: List[Dict]) -> Dict:
    """Score one activity. `history` = the user's runs (for the effort baseline),
    `races` = calendar races near its date, `planned` = the user's plan races."""
    reasons, score = [], 0.0
    day = a.local_date
    km = a.distance / 1000

    name = _plain(a.name)
    strong = STRONG.search(name)
    if strong:
        score += STRONG_WEIGHT
        reasons.append({'code': 'name', 'detail': strong.group(0)})
    elif not DEFAULT_NAME.match(name):
        weak = WEAK.findall(name)
        if weak:
            score += WEAK_WEIGHT * min(2, len(weak))
            reasons.append({'code': 'name', 'detail': ' '.join(weak)})

    for p in planned:
        if abs((p['date'] - day).days) <= 1 and (p['km'] is None or _same_distance(km, p['km'])):
            score += PLANNED_WEIGHT
            reasons.append({'code': 'planned', 'detail': p['name'], 'race_id': p['race_id']})
            break
    else:
        # Place is required: date + distance alone matches some race somewhere
        # in the world almost every weekend (4k races in the calendar).
        best = None
        for r in races:
            if abs((r.date - day).days) > 1 or not _same_distance(km, r.distance_km):
                continue
            d = _haversine_km(a.start_lat, a.start_lng, r.lat, r.lon)
            if d is not None and d <= CALENDAR_PLACE_KM and (best is None or d < best[0]):
                best = (d, r)
        if best:
            score += CALENDAR_WEIGHT
            reasons.append({'code': 'calendar', 'detail': best[1].name, 'race_id': best[1].id})

    mine = _norm_pace(a)
    base = [p for p in (_norm_pace(h) for h in history
                        if h.id != a.id and timedelta(0) < a.start_date - h.start_date <= timedelta(days=365))
            if p]
    if mine and len(base) >= 5:
        ratio = mine / statistics.median(base)
        if ratio <= EFFORT_MILD:
            score += 0.3 if ratio <= EFFORT_STRONG else 0.15
            reasons.append({'code': 'effort', 'detail': round(100 * (1 - ratio))})

    start = a.start_date_local or a.start_date
    if start.weekday() >= 5 and 5 <= start.hour < 11:  # ultras start before dawn
        score += WEEKEND_WEIGHT
        reasons.append({'code': 'weekend_morning', 'detail': None})

    return {'score': round(min(1.0, score), 2), 'reasons': reasons}


def _planned_races(user_id: int) -> List[Dict]:
    out = []
    for p in TrainingPlan.query.filter(TrainingPlan.user_id == user_id, TrainingPlan.race_date.isnot(None)):
        race = db.session.get(Race, p.race_id) if p.race_id else None
        out.append({'date': p.race_date.date(), 'name': race.name if race else p.plan_name,
                    'km': race.distance_km if race else None, 'race_id': p.race_id})
    return out


def _summary(a, extra: Optional[Dict] = None) -> Dict:
    return {'id': a.id, 'name': a.name, 'date': a.local_date.isoformat(),
            'distance_km': round(a.distance / 1000, 1), 'elevation_gain_m': round(a.elevation_gain_m or 0),
            'moving_time_s': a.moving_time_s, 'is_race': a.is_race, 'race_source': a.race_source,
            **(extra or {})}


def race_overview(user_id: int, now: Optional[datetime] = None) -> Dict:
    """Races already marked, undecided candidates, and whether a recent race exists."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    since = now - timedelta(days=LOOKBACK_DAYS)
    runs = (Activity.query.options(defer(Activity._streams))
            .filter(Activity.user_id == user_id, Activity.sport_type.in_(RUN_TYPES),
                    Activity.distance >= 3000, Activity.start_date >= since - timedelta(days=365))
            .order_by(Activity.start_date).all())
    recent = [a for a in runs if a.start_date >= since]
    races = []
    if recent:
        races = Race.query.filter(Race.date >= recent[0].local_date - timedelta(days=1),
                                  Race.date <= recent[-1].local_date + timedelta(days=1)).all()
    by_day: Dict = {}
    for r in races:
        by_day.setdefault(r.date, []).append(r)
    planned = _planned_races(user_id)

    candidates = []
    for a in recent:
        if a.race_source is not None or a.is_race:
            continue
        near = [r for d in (-1, 0, 1) for r in by_day.get(a.local_date + timedelta(days=d), [])]
        s = score_activity(a, runs, near, planned)
        if s['score'] >= CANDIDATE_MIN_SCORE:
            candidates.append(_summary(a, s))
    candidates.sort(key=lambda c: (-c['score'], c['date']))

    marked = [_summary(a) for a in reversed(recent) if a.is_race]
    year_ago = (now - timedelta(days=365)).date().isoformat()
    return {
        'marked': marked,
        'candidates': candidates[:10],
        'has_recent_race': any(m['date'] >= year_ago for m in marked),
    }

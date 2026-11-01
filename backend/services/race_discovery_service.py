"""Find a race on the web and add it to the calendar.

Flow: DuckDuckGo HTML search -> fetch the top pages -> the agent LLM reads
their text and returns the race as JSON (next edition, courses, poster, GPX
links) -> one ``Race`` row per course, with the poster and GPX stored in the
row (the backend container has no persistent disk).

Best effort: a page that fails to load is skipped; a race with no GPX found
online is still saved, without track.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import date
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import gpxpy
import gpxpy.gpx
import requests

from database import db
from models.race import Race

logger = logging.getLogger(__name__)

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'
TIMEOUT = 10
MAX_PAGES = 6
PAGE_CHARS = 5000
MAX_POSTER_BYTES = 3 * 1024 * 1024
MAX_GPX_BYTES = 10 * 1024 * 1024
POSTER_HINT = re.compile(r'locandin|poster|volantin|flyer|manifesto|og:image', re.IGNORECASE)


class _PageParser(HTMLParser):
    """Visible text, image URLs and links of one HTML page (stdlib only)."""

    def __init__(self):
        super().__init__()
        self.text: list[str] = []
        self.images: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style', 'noscript'):
            self._skip += 1
        elif tag == 'img' and a.get('src'):
            self.images.append(a['src'] + ' ' + (a.get('alt') or ''))
        elif tag == 'meta' and a.get('property') == 'og:image' and a.get('content'):
            self.images.insert(0, a['content'] + ' og:image')
        elif tag == 'a' and a.get('href'):
            self.links.append(a['href'])

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.text.append(data.strip())


def search_web(query: str, limit: int = MAX_PAGES) -> list[str]:
    """Result URLs from DuckDuckGo's HTML endpoint (no API key needed)."""
    r = requests.post('https://html.duckduckgo.com/html/', data={'q': query},
                      headers={'User-Agent': UA}, timeout=TIMEOUT)
    r.raise_for_status()
    urls = []
    for href in re.findall(r'class="result__a" href="([^"]+)"', r.text):
        # Ads and some results are wrapped in a /l/?uddg=<url> redirect.
        if 'uddg=' in href:
            href = unquote(parse_qs(urlparse(href).query).get('uddg', [''])[0])
        if href.startswith('http') and 'duckduckgo.com' not in href and href not in urls:
            urls.append(href)
    return urls[:limit]


def _fetch_page(url: str) -> dict[str, Any] | None:
    try:
        r = requests.get(url, headers={'User-Agent': UA}, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.info('race discovery: skip %s (%s)', url, e)
        return None
    p = _PageParser()
    p.feed(r.text)
    images = []
    for img in p.images:
        src = img.partition(' ')[0]
        if POSTER_HINT.search(img):
            images.append(urljoin(url, src))
    gpx = [urljoin(url, h) for h in p.links if re.search(r'\.gpx(\?|$)|gpx', h, re.IGNORECASE)]
    gpx.sort(key=lambda h: not re.search(r'\.gpx(\?|$)', h, re.IGNORECASE))  # real files first
    text = ' '.join(p.text)
    pts = _tracedetrail_points(r.text)
    if pts:
        # The track itself is the GPX source; its totals help the LLM match the course.
        gpx.insert(0, url)
        text = f"TRACK ON THIS PAGE: {pts[-1].get('x')} km, D+ {pts[-1].get('dp')} m. " + text
    return {
        'url': url,
        'text': text[:PAGE_CHARS],
        'poster_candidates': list(dict.fromkeys(images))[:8],
        'gpx_candidates': list(dict.fromkeys(gpx))[:8],
    }


PROMPT = """You read web pages about a running race and return it as JSON.
Today is {today}. The user searched for: "{query}".

Return ONLY a JSON object, no prose:
{{"found": true|false,
  "name": "official race name",
  "date": "YYYY-MM-DD of the NEXT edition on or after today",
  (races are almost always on Saturday or Sunday: when sources disagree, trust the official site, then the date on a weekend)
  "date_estimated": true if the next edition's date is not published and you inferred it from past editions (same weekend next year),
  "location": "town, province", "region": "...", "country": "ISO-2",
  "lat": number|null, "lon": number|null  (start town),
  "url": "official site or best page",
  "description": "2-3 sentences in Italian: format, terrain, notable climbs, organizer",
  "poster_url": one of the poster_candidates that is the race poster, or null,
  "courses": [{{"label": "e.g. Long Trail", "distance_km": number, "elev_gain_m": number|null,
               "race_type": "trail|road|ultra|vertical", "surface": "trail|asphalt|mixed",
               "gpx_url": one of the gpx_candidates for this course, or null}}]}}
For gpx_url prefer a direct .gpx file or a "TRACK ON THIS PAGE" url whose distance matches the course;
a track from a past edition is fine when the course is the same distance.
Use only facts from the pages. The official site beats aggregators (calendars often copy last
year's courses): take date, courses and D+ from the official site's newest edition when it has them. If the pages are not about this race, return {{"found": false}}.

PAGES:
{pages}"""


def _ask_llm(query: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    from config import agent_config
    from services.agent.agent_service import _get_client

    body = PROMPT.format(today=date.today().isoformat(), query=query,
                         pages=json.dumps(pages, ensure_ascii=False))
    kwargs = {'extra_body': agent_config.AGENT_EXTRA_BODY} if agent_config.AGENT_EXTRA_BODY else {}
    resp = _get_client().messages.create(
        model=agent_config.AGENT_MODEL, max_tokens=2000,
        messages=[{'role': 'user', 'content': body}], **kwargs)
    text = ''.join(getattr(b, 'text', '') for b in resp.content)
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        raise ValueError('LLM returned no JSON')
    return json.loads(m.group(0))


def _download(url: str | None, max_bytes: int) -> requests.Response | None:
    if not url or not url.startswith('http'):
        return None
    try:
        r = requests.get(url, headers={'User-Agent': UA}, timeout=TIMEOUT * 2)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.info('race discovery: download failed %s (%s)', url, e)
        return None
    return r if len(r.content) <= max_bytes else None


def _tracedetrail_points(html: str) -> list[dict] | None:
    """Track points embedded in a tracedetrail.fr trace page, else None.

    The page inlines ``geometry:"<json>"``: points in Web Mercator (lon/lat in
    metres), ``y`` = elevation, ``x`` = cumulative km, ``dp`` = cumulative D+.
    """
    m = re.search(r'geometry:"((?:[^"\\]|\\.)*)"', html)
    if not m:
        return None
    try:
        pts = json.loads(json.loads(f'"{m.group(1)}"'))
    except ValueError:
        return None
    return pts if isinstance(pts, list) and len(pts) > 1 else None


def _points_to_gpx(pts: list[dict], name: str = '') -> str:
    r = 6378137.0
    g = gpxpy.gpx.GPX()
    trk = gpxpy.gpx.GPXTrack(name=name or None)
    seg = gpxpy.gpx.GPXTrackSegment()
    for p in pts:
        lat = math.degrees(2 * math.atan(math.exp(p['lat'] / r)) - math.pi / 2)
        seg.points.append(gpxpy.gpx.GPXTrackPoint(lat, math.degrees(p['lon'] / r), elevation=p.get('y')))
    trk.segments.append(seg)
    g.tracks.append(trk)
    return g.to_xml()


def _valid_gpx(url: str | None) -> str | None:
    r = _download(url, MAX_GPX_BYTES)
    if r is None:
        return None
    pts = _tracedetrail_points(r.text)
    if pts:
        return _points_to_gpx(pts)
    try:
        g = gpxpy.parse(r.text)
    except Exception:  # noqa: BLE001 - any parse failure means "not a GPX"
        return None
    has_points = any(s.points for t in g.tracks for s in t.segments) or any(rt.points for rt in g.routes)
    return r.text if has_points else None


def _load_tracks(urls: list[str]) -> list[tuple[float, str]]:
    """(length_km, gpx) of every candidate that is really a track (max 6 downloads)."""
    out = []
    for url in list(dict.fromkeys(urls))[:6]:
        gpx = _valid_gpx(url)
        if gpx:
            out.append((gpxpy.parse(gpx).length_2d() / 1000, gpx))
    return out


def _match_gpx(tracks: list[tuple[float, str]] | None, distance_km: float) -> str | None:
    """Track whose length is closest to the course, within 12 % (GPS vs official km)."""
    best = min(tracks or [], key=lambda t: abs(t[0] - distance_km), default=None)
    return best[1] if best and abs(best[0] - distance_km) <= 0.12 * distance_km else None


def _geocode(place: str, country: str | None) -> tuple[float | None, float | None]:
    """Town -> (lat, lon) via OSM Nominatim (1 request per discovery, within its usage policy)."""
    try:
        r = requests.get('https://nominatim.openstreetmap.org/search',
                         params={'q': place, 'format': 'json', 'limit': 1,
                                 **({'countrycodes': country.lower()} if country else {})},
                         headers={'User-Agent': 'PaceMind race discovery'}, timeout=TIMEOUT)
        hit = r.json()[0]
        return float(hit['lat']), float(hit['lon'])
    except (requests.RequestException, ValueError, IndexError, KeyError):
        return None, None


def _slugify(value: str) -> str:
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]', '-', value.lower())).strip('-')


def _existing_course(base_name: str, year: int, distance_km: float) -> Race | None:
    """Web race already saved for this edition and course.

    The LLM labels courses differently on each run ('21 km' vs 'Corto') and
    sources round distances differently (19 vs 21 km), so match on the base
    name + year + distance within 12 % instead of the label.
    """
    rows = Race.query.filter(Race.source == 'web', Race.name.ilike(f'{base_name}%'),
                             Race.external_id.like(f'%-{year}')).all()
    rows = [r for r in rows if abs(r.distance_km - distance_km) <= 0.12 * distance_km]
    return min(rows, key=lambda r: abs(r.distance_km - distance_km), default=None)


def save_race(info: dict[str, Any], gpx_pool: list[str] = ()) -> list[Race]:
    """Upsert one Race per course (source='web'); idempotent on name+date+label."""
    race_date = date.fromisoformat(info['date'])
    poster = _download(info.get('poster_url'), MAX_POSTER_BYTES)
    poster_ok = poster is not None and poster.headers.get('Content-Type', '').startswith('image/')
    saved = []
    tracks = None if all(c.get('gpx_url') for c in info.get('courses') or []) else _load_tracks(gpx_pool)
    for course in info.get('courses') or []:
        if not course.get('distance_km'):
            continue
        name = info['name'] if len(info['courses']) == 1 else f"{info['name']} - {course.get('label') or course['distance_km']}"
        ext_id = _slugify(f"{name}-{race_date.year}")
        race = _existing_course(info['name'], race_date.year, float(course['distance_km'])) or Race(
            source='web', external_id=ext_id, slug=_slugify(f'web-{ext_id}'))
        race.name = name
        race.date = race_date
        race.date_estimated = bool(info.get('date_estimated'))
        race.url = info.get('url')
        race.description = info.get('description')
        race.location = info.get('location')
        race.region = info.get('region')
        race.country = (info.get('country') or '')[:2].upper() or None
        race.lat, race.lon = info.get('lat'), info.get('lon')
        race.distance_km = float(course['distance_km'])
        race.elev_gain_m = course.get('elev_gain_m')
        race.race_type = course.get('race_type')
        race.surface = course.get('surface')
        if poster_ok:
            race.poster_data = poster.content
            race.poster_mime = poster.headers['Content-Type'].split(';')[0]
        gpx = _valid_gpx(course.get('gpx_url')) or _match_gpx(tracks, race.distance_km)
        if gpx:
            if not race.elev_gain_m:
                race.elev_gain_m = round(gpxpy.parse(gpx).get_uphill_downhill().uphill)
            race.gpx_data = gpx
            if race.lat is None:
                first = gpxpy.parse(gpx).tracks[0].segments[0].points[0]
                race.lat, race.lon = first.latitude, first.longitude
        if race.lat is None and info.get('location'):
            race.lat, race.lon = _geocode(info['location'], info.get('country'))
        db.session.add(race)
        saved.append(race)
    db.session.commit()
    return saved


def import_race_gpx(race: Race, user_id: int):
    """Copy the race GPX into the user's routes so prediction tools can use it.

    Idempotent: reuses the route already imported from this race, refreshing
    its track (a later discovery may have found the new edition's GPX).
    """
    import os
    import tempfile

    from models import GPXFile
    from services.data_processor import process_gpx_data
    from services.gpx_parser import parse_gpx_file

    with tempfile.NamedTemporaryFile('w', suffix='.gpx', delete=False) as f:
        f.write(race.gpx_data)
    try:
        data = process_gpx_data(parse_gpx_file(f.name))
    finally:
        os.unlink(f.name)
    # The parsed track lives in `data`; file_path only records where it came from.
    gpx = GPXFile.query.filter_by(user_id=user_id, file_path=f'race:{race.id}').first()
    if gpx is None:
        filename = f'race-{race.id}-{race.slug}.gpx'
        gpx = GPXFile(user_id=user_id, filename=filename, original_filename=filename,
                      file_path=f'race:{race.id}')
        db.session.add(gpx)
    gpx.data = data
    db.session.commit()
    return gpx


def discover_race(query: str) -> list[Race]:
    """Search the web for ``query`` and save what is found. [] = not found."""
    # Second search for the track: race sites rarely host the GPX themselves.
    # The official site often ranks low for the bare name, so it gets its own query, first.
    urls = list(dict.fromkeys(search_web(f'{query} sito ufficiale', 3) + search_web(f'{query} trail gara')
                              + search_web(f'{query} gpx')))[:MAX_PAGES + 3]
    pages = [p for p in (_fetch_page(u) for u in urls) if p]
    if not pages:
        return []
    info = _ask_llm(query, pages)
    if not info.get('found') or not info.get('date') or not info.get('name'):
        return []
    # Deterministic fallback when the LLM leaves gpx_url empty: real files only.
    pool = [u for p in pages for u in p['gpx_candidates']
            if re.search(r'\.gpx(\?|$)', u, re.IGNORECASE) or u == p['url']]
    return save_race(info, pool)

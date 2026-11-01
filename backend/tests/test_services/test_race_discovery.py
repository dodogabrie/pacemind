"""Web race discovery: page parsing, upsert per course, GPX validation (no network)."""

from unittest.mock import patch

import pytest

from app import create_app
from database import db
from models import Race
from services import race_discovery_service as rd

GPX = ('<?xml version="1.0"?><gpx version="1.1" creator="t"><trk><trkseg>'
       '<trkpt lat="43.75" lon="10.43"><ele>20</ele></trkpt>'
       '<trkpt lat="43.76" lon="10.44"><ele>80</ele></trkpt></trkseg></trk></gpx>')


@pytest.fixture
def app():
    app = create_app()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_page_parser_finds_text_poster_and_gpx():
    p = rd._PageParser()
    p.feed('<html><head><meta property="og:image" content="/img/locandina.jpg"><script>x=1</script></head>'
           '<body><h1>Penna Trail</h1><img src="logo.png"><a href="/files/long.gpx">GPX</a></body></html>')
    assert 'Penna Trail' in ' '.join(p.text) and 'x=1' not in ' '.join(p.text)
    assert p.images[0].startswith('/img/locandina.jpg')
    assert '/files/long.gpx' in p.links


class _Resp:
    def __init__(self, text):
        self.text, self.content, self.headers = text, text.encode(), {'Content-Type': 'application/gpx+xml'}


def test_save_race_one_row_per_course_and_idempotent(app):
    info = {'name': 'Penna Trail Run', 'date': '2027-01-31', 'date_estimated': True,
            'location': 'Molina di Quosa (PI)', 'country': 'it', 'lat': 43.75, 'lon': 10.43,
            'courses': [{'label': 'Long', 'distance_km': 33, 'elev_gain_m': 1700, 'gpx_url': 'https://x/long.gpx'},
                        {'label': 'Short', 'distance_km': 19, 'elev_gain_m': 800, 'gpx_url': 'https://x/bad.gpx'}]}
    with patch.object(rd, '_download', side_effect=lambda url, _m: _Resp(GPX if url and 'long' in url else 'not xml') if url else None):
        rd.save_race(info)
        rd.save_race(info)
    rows = Race.query.order_by(Race.distance_km.desc()).all()
    assert [r.name for r in rows] == ['Penna Trail Run - Long', 'Penna Trail Run - Short']
    assert rows[0].has_gpx and not rows[1].has_gpx
    assert rows[0].country == 'IT' and rows[0].date_estimated and rows[0].source == 'web'
    assert rows[0].to_dict()['has_poster'] is False


def test_tracedetrail_page_becomes_gpx():
    html = 'var t = {geometry:"[{\\"lon\\":1159728.6,\\"lat\\":5433996.1,\\"y\\":6,\\"x\\":0,\\"dp\\":0},' \
           '{\\"lon\\":1159294.5,\\"lat\\":5431251.4,\\"y\\":5,\\"x\\":33.66,\\"dp\\":1637}]"}'
    pts = rd._tracedetrail_points(html)
    assert pts[-1]['dp'] == 1637
    import gpxpy
    first = gpxpy.parse(rd._points_to_gpx(pts)).tracks[0].segments[0].points[0]
    assert abs(first.latitude - 43.7964) < 0.01 and abs(first.longitude - 10.4180) < 0.01


def test_match_gpx_picks_closest_length_within_tolerance():
    tracks = [(19.4, 'short'), (33.7, 'long')]
    assert rd._match_gpx(tracks, 34) == 'long'
    assert rd._match_gpx(tracks, 21) == 'short'
    assert rd._match_gpx(tracks, 50) is None
    assert rd._match_gpx(None, 34) is None


def test_find_race_online_tool_uses_calendar_and_imports_gpx_once(app):
    from datetime import date

    from models import GPXFile, User
    from services.agent.tool_handlers.race import _handle_find_race_online

    user = User(strava_user_id=1, email='t@example.com')
    race = Race(source='web', external_id='penna', slug='web-penna', name='Penna Trail Run - Long',
                date=date(2099, 2, 7), distance_km=33, gpx_data=GPX)
    db.session.add_all([user, race])
    db.session.commit()
    with patch.object(rd, 'discover_race', side_effect=AssertionError('no web when in calendar')):
        a = _handle_find_race_online({'query': 'Penna Trail', 'import_gpx': True}, user.id)
        b = _handle_find_race_online({'query': 'Penna Trail', 'import_gpx': True}, user.id)
    assert a['source'] == 'calendar' and a['races'][0]['has_gpx']
    assert a['races'][0]['gpx_id'] == b['races'][0]['gpx_id']
    assert GPXFile.query.filter_by(user_id=user.id).count() == 1


def test_save_race_matches_course_relabelled_by_llm(app):
    base = {'name': 'Penna Trail Run', 'date': '2027-02-07', 'location': 'Molina di Quosa', 'lat': 1, 'lon': 1}
    with patch.object(rd, '_download', return_value=None):
        rd.save_race({**base, 'courses': [{'label': '21 km', 'distance_km': 21}, {'label': '34 km', 'distance_km': 34}]})
        rd.save_race({**base, 'courses': [{'label': 'Corto', 'distance_km': 19}, {'label': 'Lungo', 'distance_km': 33}]})
    assert sorted(r.distance_km for r in Race.query.all()) == [19, 33]

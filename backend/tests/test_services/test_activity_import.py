"""Multi-format file ingest — the guards, the filters, and the failure modes.

Phase 2 of the multi-source epic
(docs/plans/multi-source-activities/03-file-ingest.md). What this file locks in:

* a hostile archive cannot bomb us or write outside the job directory
* cycling and swimming from the same export never reach training load
* one corrupt file is a reported skip, not an aborted import
* re-dropping the same archive is a no-op

The FIT fixtures are synthesised here rather than committed as binaries: a
handful of bytes of the real wire format is cheaper to review than a blob, and
it keeps the repo free of vendor data.
"""

import os
import struct
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest

from app import create_app
from database import db
from models import Activity, User
from services.activity_import_service import ActivityImportService
from services.activity_ingest import ActivityIngestService
from services.activity_ingest.archive import ArchiveRejected, iter_activity_files
from services.activity_ingest.normalizers import is_supported_sport, map_sport

START = datetime(2026, 3, 14, 6, 30, 0, tzinfo=timezone.utc)


# ── fixtures ────────────────────────────────────────────────────────────────

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


@pytest.fixture
def user_id(app):
    u = User(strava_user_id=4242, strava_username='importer')
    db.session.add(u)
    db.session.commit()
    return u.id


class _NoResiduals:
    """Residual collection is the ML layer's business, not this suite's."""

    def collect_residuals_from_activity(self, **kwargs):
        return None


@pytest.fixture
def service(tmp_path):
    from services.cache_service import CacheService
    ingest = ActivityIngestService(
        cache_service=CacheService(cache_dir=str(tmp_path / 'cache')),
        residual_service=_NoResiduals())
    return ActivityImportService(ingest_service=ingest)


def run_import(service, user_id, files, tmp_path, name='export.zip'):
    """Zip `files` ({member_name: bytes}) and import it. Returns the summary."""
    job_dir = tmp_path / f'job_{name}'
    job_dir.mkdir(exist_ok=True)
    path = job_dir / name
    with zipfile.ZipFile(path, 'w') as zf:
        for member, data in files.items():
            zf.writestr(member, data)
    return service.run(user_id, str(path), str(job_dir))


# ── file builders ───────────────────────────────────────────────────────────

def gpx_bytes(start=START, points=60, sport='running'):
    rows = []
    for i in range(points):
        t = (start + timedelta(seconds=i * 5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        rows.append(
            f'<trkpt lat="{45.0 + i * 0.0002:.6f}" lon="{7.0 + i * 0.0002:.6f}">'
            f'<ele>{300 + i * 2}</ele><time>{t}</time></trkpt>')
    return (
        '<?xml version="1.0"?>'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f'<trk><name>Morning run</name><type>{sport}</type><trkseg>'
        + ''.join(rows) +
        '</trkseg></trk></gpx>').encode()


def tcx_bytes(sport='Running', start=START, points=60):
    rows = []
    for i in range(points):
        t = (start + timedelta(seconds=i * 5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        rows.append(
            f'<Trackpoint><Time>{t}</Time><Position>'
            f'<LatitudeDegrees>{45.0 + i * 0.0002:.6f}</LatitudeDegrees>'
            f'<LongitudeDegrees>{7.0 + i * 0.0002:.6f}</LongitudeDegrees>'
            f'</Position><AltitudeMeters>{300 + i * 2}</AltitudeMeters>'
            f'<DistanceMeters>{i * 15}</DistanceMeters>'
            f'<HeartRateBpm><Value>{140 + i % 5}</Value></HeartRateBpm>'
            f'</Trackpoint>')
    return (
        '<?xml version="1.0"?>'
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/'
        'TrainingCenterDatabase/v2"><Activities>'
        f'<Activity Sport="{sport}"><Id>2026-03-14T06:30:00Z</Id><Lap><Track>'
        + ''.join(rows) +
        '</Track></Lap></Activity></Activities></TrainingCenterDatabase>').encode()


# --- minimal FIT writer -----------------------------------------------------

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
_CRC_TABLE = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
              0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)


def _fit_crc(data):
    crc = 0
    for byte in data:
        for nibble in (byte & 0x0F, (byte >> 4) & 0x0F):
            tmp = _CRC_TABLE[crc & 0x0F]
            crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[nibble]
    return crc


def _definition(local, global_num, fields):
    body = struct.pack('<BBHB', 0, 0, global_num, len(fields))
    body += b''.join(struct.pack('<BBB', num, size, base) for num, size, base in fields)
    return bytes([0x40 | local]) + body


def fit_bytes(sport=1, sub_sport=3, start=START, points=60):
    """A tiny but real FIT file: file_id + session + N record messages.

    `sport` follows the FIT profile enum — 1 running, 2 cycling, 17 hiking.
    """
    ts = int((start - FIT_EPOCH).total_seconds())
    data = b''

    # file_id: type=4 (activity), manufacturer, product, time_created
    data += _definition(0, 0, [(0, 1, 0x00), (1, 2, 0x84), (4, 4, 0x86)])
    data += bytes([0x00]) + struct.pack('<BHI', 4, 1, ts)

    # record: timestamp, position_lat, position_long, distance, altitude, hr
    data += _definition(1, 20, [(253, 4, 0x86), (0, 4, 0x85), (1, 4, 0x85),
                                (5, 4, 0x86), (2, 2, 0x84), (3, 1, 0x02)])
    scale = (2 ** 31) / 180.0
    for i in range(points):
        lat = int((45.0 + i * 0.0002) * scale)
        lon = int((7.0 + i * 0.0002) * scale)
        altitude = int(((300 + i * 2) + 500) * 5)          # scale 5, offset -500
        data += bytes([0x01]) + struct.pack(
            '<IiiIHB', ts + i * 5, lat, lon, i * 1500, altitude, 145)

    # session: start_time, total_elapsed_time, total_timer_time, total_distance,
    #          total_ascent, sport, sub_sport
    data += _definition(2, 18, [(2, 4, 0x86), (7, 4, 0x86), (8, 4, 0x86),
                                (9, 4, 0x86), (22, 2, 0x84),
                                (5, 1, 0x00), (6, 1, 0x00)])
    data += bytes([0x02]) + struct.pack(
        '<IIIIHBB', ts, points * 5 * 1000, points * 5 * 1000,
        points * 1500, points * 2, sport, sub_sport)

    header = struct.pack('<BBHI4s', 12, 0x10, 2100, len(data), b'.FIT')
    body = header + data
    return body + struct.pack('<H', _fit_crc(body))


# ── security guards ─────────────────────────────────────────────────────────

def test_zip_bomb_is_refused_on_declared_size(tmp_path, monkeypatch):
    """A member that claims to expand past the cap never gets read at all."""
    from services.activity_ingest import archive
    monkeypatch.setattr(archive, 'MAX_TOTAL_BYTES', 1024)

    path = tmp_path / 'bomb.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('bomb.gpx', b'0' * (5 * 1024 * 1024))  # compresses to ~5 KB

    with pytest.raises(ArchiveRejected, match='limit'):
        list(iter_activity_files(str(path)))


def test_zip_bomb_is_refused_on_member_size(tmp_path, monkeypatch):
    from services.activity_ingest import archive
    monkeypatch.setattr(archive, 'MAX_MEMBER_BYTES', 1024)

    path = tmp_path / 'big.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('big.gpx', b'0' * (1024 * 1024))

    results = list(iter_activity_files(str(path)))
    assert [(name, err) for name, _, err in results] == [('big.gpx', 'file too large')]


def test_member_count_is_capped(tmp_path, monkeypatch):
    from services.activity_ingest import archive
    monkeypatch.setattr(archive, 'MAX_MEMBERS', 3)

    path = tmp_path / 'many.zip'
    with zipfile.ZipFile(path, 'w') as zf:
        for i in range(5):
            zf.writestr(f'{i}.gpx', b'x')

    with pytest.raises(ArchiveRejected, match='entries'):
        list(iter_activity_files(str(path)))


def test_path_traversal_member_is_skipped_and_writes_nothing(tmp_path, user_id,
                                                             service):
    """`../../` members are reported, never opened, never written."""
    escape = '../../../../tmp/pacemind_traversal_probe.gpx'
    summary = run_import(service, user_id,
                         {escape: gpx_bytes(), 'ok.gpx': gpx_bytes()},
                         tmp_path, name='evil.zip')

    assert summary['imported'] == 1
    assert [s['reason'] for s in summary['skipped_files']] == ['unsafe path in archive']
    assert not os.path.exists('/tmp/pacemind_traversal_probe.gpx')


def test_xml_with_a_dtd_is_refused(tmp_path, user_id, service):
    """Billion-laughs class: stdlib ElementTree expands entities, so no DTDs."""
    bomb = (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
            b'<gpx></gpx>')
    summary = run_import(service, user_id, {'lol.gpx': bomb}, tmp_path,
                         name='dtd.zip')

    assert summary['imported'] == 0
    assert 'DTD' in summary['skipped_files'][0]['reason']


# ── processing rules ────────────────────────────────────────────────────────

def test_sport_filter_keeps_running_and_drops_the_rest(tmp_path, user_id, service):
    summary = run_import(service, user_id, {
        'runs/morning.gpx': gpx_bytes(),
        'runs/trail.fit': fit_bytes(sport=1, sub_sport=3),
        'rides/commute.tcx': tcx_bytes(sport='Biking', start=START + timedelta(days=1)),
        'rides/sunday.fit': fit_bytes(sport=2, sub_sport=0, start=START + timedelta(days=2)),
    }, tmp_path, name='mixed.zip')

    assert summary['imported'] == 2
    assert {s['name'] for s in summary['skipped_files']} == {'rides/commute.tcx',
                                                             'rides/sunday.fit'}
    assert all('not a running activity' in s['reason']
               for s in summary['skipped_files'])

    sports = {a.sport_type for a in Activity.query.filter_by(user_id=user_id)}
    assert sports == {'run', 'trail_run'}


def test_fit_sport_vocabulary():
    assert map_sport('running', 'trail') == 'trail_run'
    assert map_sport('running', 'generic') == 'run'
    assert map_sport('hiking') == 'hike'
    assert map_sport('cycling') == 'other'
    assert map_sport('swimming') == 'other'
    assert map_sport(None) is None
    assert is_supported_sport(None)          # a bare GPX says nothing; allow it
    assert not is_supported_sport('other')


def test_corrupt_file_is_reported_not_fatal(tmp_path, user_id, service):
    summary = run_import(service, user_id, {
        'good.gpx': gpx_bytes(),
        'broken.fit': b'\x00\x01\x02not a fit file at all',
        'truncated.tcx': b'<TrainingCenterDatabase><Activities>',
        'empty.gpx': b'',
    }, tmp_path, name='partial.zip')

    assert summary['imported'] == 1
    assert {s['name'] for s in summary['skipped_files']} == {'broken.fit',
                                                             'truncated.tcx',
                                                             'empty.gpx'}
    assert Activity.query.filter_by(user_id=user_id).count() == 1


def test_reimporting_the_same_archive_is_a_no_op(tmp_path, user_id, service):
    files = {'a.gpx': gpx_bytes(), 'b.fit': fit_bytes(start=START + timedelta(days=1))}

    first = run_import(service, user_id, files, tmp_path, name='first.zip')
    second = run_import(service, user_id, files, tmp_path, name='second.zip')

    assert first['imported'] == 2
    assert second['imported'] == 2          # re-ingested, but onto the same rows
    assert Activity.query.filter_by(user_id=user_id).count() == 2


def test_gz_members_are_decompressed(tmp_path, user_id, service):
    """Strava archives ship every activity gzipped."""
    import gzip
    summary = run_import(service, user_id,
                         {'activities/1234.gpx.gz': gzip.compress(gpx_bytes())},
                         tmp_path, name='strava.zip')
    assert summary['imported'] == 1


def test_job_directory_is_removed_when_the_import_ends(tmp_path, user_id, service):
    job_dir = tmp_path / 'job_cleanup'
    job_dir.mkdir()
    path = job_dir / 'export.zip'
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('a.gpx', gpx_bytes())

    service.run(user_id, str(path), str(job_dir))
    assert not job_dir.exists()


def test_status_row_reports_the_summary(tmp_path, user_id, service):
    from repositories import SyncStatusRepository

    run_import(service, user_id,
               {'a.gpx': gpx_bytes(), 'bad.fit': b'nope'},
               tmp_path, name='status.zip')

    status = SyncStatusRepository().get_for_user(user_id, 'upload')
    assert status.status == 'completed'
    assert status.message == '1 imported, 1 skipped'
    assert 'bad.fit' in status.error_message   # the result summary, as JSON


# ── the parsed result ───────────────────────────────────────────────────────

def test_fit_activity_lands_with_streams_and_totals(tmp_path, user_id, service):
    run_import(service, user_id, {'run.fit': fit_bytes()}, tmp_path, name='fit.zip')

    activity = Activity.query.filter_by(user_id=user_id).one()
    assert activity.source == 'upload_fit'
    assert activity.sport_type == 'trail_run'
    assert activity.start_date.replace(tzinfo=timezone.utc) == START
    # Sensor distance from the session record, not recomputed from GPS.
    assert activity.distance == pytest.approx(60 * 1500 / 100.0, rel=0.01)
    assert set(activity.streams) >= {'time', 'distance', 'altitude', 'latlng',
                                     'velocity_smooth', 'grade_smooth',
                                     'heartrate'}
    assert activity.streams['heartrate'][0] == 145


def test_tcx_activity_keeps_its_recorded_distance(tmp_path, user_id, service):
    run_import(service, user_id, {'polar.tcx': tcx_bytes()}, tmp_path,
               name='tcx.zip')

    activity = Activity.query.filter_by(user_id=user_id).one()
    assert activity.source == 'upload_tcx'
    assert activity.distance == pytest.approx(59 * 15, rel=0.01)
    assert activity.streams['heartrate'][0] == 140


def test_local_calendar_day_comes_from_the_start_coordinates(tmp_path, user_id,
                                                             service):
    """22:00 in New Zealand is the *next* UTC day — bucket it locally."""
    late = datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc)  # 22:00 at lon 174
    body = gpx_bytes(start=late).replace(b'lon="7.', b'lon="174.')

    run_import(service, user_id, {'nz.gpx': body}, tmp_path, name='nz.zip')

    activity = Activity.query.filter_by(user_id=user_id).one()
    assert activity.start_date.date() == datetime(2026, 3, 14).date()
    assert activity.local_date == datetime(2026, 3, 14).date()
    assert activity.start_date_local.hour == 21   # lon 174 -> UTC+12


def test_loose_file_upload_without_an_archive(tmp_path, user_id, service):
    job_dir = tmp_path / 'job_loose'
    job_dir.mkdir()
    path = job_dir / 'single.gpx'
    path.write_bytes(gpx_bytes())

    summary = service.run(user_id, str(path), str(job_dir))
    assert summary['imported'] == 1


def test_import_endpoints_require_auth(app):
    client = app.test_client()
    assert client.post('/api/activities/import').status_code == 401
    assert client.get('/api/activities/import').status_code == 401
    assert client.delete('/api/activities/import').status_code == 401


def test_fit_bytes_fixture_is_a_real_fit_file():
    """Guard the fixture itself: a broken writer would fake every FIT test."""
    from fitparse import FitFile

    fit = FitFile(BytesIO(fit_bytes()))
    records = [m.get_values() for m in fit.get_messages('record')]
    assert len(records) == 60
    assert records[0]['heart_rate'] == 145
    assert [m.get_values()['sport'] for m in fit.get_messages('session')] == ['running']

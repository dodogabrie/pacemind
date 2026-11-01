"""Safe iteration over an uploaded bundle of activity files.

Everything here treats the upload as hostile: it is an arbitrary zip from an
arbitrary user. The guards, in order of what they stop:

* **Zip bomb** — `MAX_MEMBERS`, `MAX_TOTAL_BYTES` and `MAX_MEMBER_BYTES`. The
  declared sizes in the central directory are checked first (cheap rejection),
  and then the *actual* decompressed bytes are counted as we read, because a
  crafted archive can lie in its headers.
* **Path traversal** — member names are validated to stay inside the job
  directory. Belt and braces: member *contents* are never written to disk at
  all, they are read straight out of the zip one at a time, so there is no
  extraction step to escape from in the first place.
* **Memory** — one member is in memory at a time and it is capped, so a
  700 MB Garmin export costs ~64 MB peak, not 700 MB.

Nested archives are not recursed into: no vendor ships one, and recursion is
how zip-bomb budgets get blown.
"""

import gzip
import logging
import os
import posixpath
import zipfile
from io import BytesIO
from typing import Iterator, Tuple

logger = logging.getLogger(__name__)

# A Garmin GDPR export is a few hundred MB of FIT; leave headroom, refuse the
# rest with a clear message rather than dying half way through.
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 20000

ACTIVITY_EXTENSIONS = ('.fit', '.tcx', '.gpx')


class ArchiveRejected(Exception):
    """The upload as a whole is unusable — nothing was imported."""


def is_activity_file(name: str) -> bool:
    stem = name[:-3] if name.lower().endswith('.gz') else name
    return stem.lower().endswith(ACTIVITY_EXTENSIONS)


def file_kind(name: str) -> str:
    """'fit' | 'tcx' | 'gpx' — the NORMALIZERS key for this filename."""
    stem = name[:-3] if name.lower().endswith('.gz') else name
    return stem.rsplit('.', 1)[-1].lower()


def is_safe_member(name: str) -> bool:
    """Would extracting `name` stay inside the job directory?

    Rejects absolute paths, drive letters, `..` segments and anything that
    normalises to an escape. Windows-style separators are normalised first
    because zip members legitimately use both.
    """
    if not name or name.endswith('/'):
        return False
    candidate = name.replace('\\', '/')
    if candidate.startswith('/') or (len(candidate) > 1 and candidate[1] == ':'):
        return False
    normalized = posixpath.normpath(candidate)
    return not (normalized.startswith('../') or normalized == '..'
                or normalized.startswith('/'))


def count_activity_files(path: str) -> int:
    """How many activity files the upload holds — for the progress total."""
    if not zipfile.is_zipfile(path):
        return 1 if is_activity_file(os.path.basename(path)) else 0
    with zipfile.ZipFile(path) as zf:
        return sum(1 for info in zf.infolist()
                   if not info.is_dir() and is_activity_file(info.filename)
                   and is_safe_member(info.filename))


def iter_activity_files(path: str) -> Iterator[Tuple[str, bytes, str]]:
    """Yield `(display_name, data, error)` for each activity file in `path`.

    `error` is non-empty for a member we refused (unsafe name, oversized); in
    that case `data` is empty. A per-member problem is reported, never raised —
    partial failure is the normal case for a vendor export. Problems with the
    *archive* raise `ArchiveRejected`, because then there is nothing to import.
    """
    if not zipfile.is_zipfile(path):
        name = os.path.basename(path)
        data, error = _read_capped_file(path)
        if not error:
            data, error = _gunzip(data, name)
        yield (name, data, error)
        return

    total = 0
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_MEMBERS:
                raise ArchiveRejected(
                    f'archive has {len(infos)} entries, the limit is {MAX_MEMBERS}')
            declared = sum(i.file_size for i in infos)
            if declared > MAX_TOTAL_BYTES:
                raise ArchiveRejected(
                    f'archive expands to {declared // (1024 * 1024)} MB, '
                    f'the limit is {MAX_TOTAL_BYTES // (1024 * 1024)} MB')

            for info in infos:
                if info.is_dir() or not is_activity_file(info.filename):
                    continue
                if not is_safe_member(info.filename):
                    yield (info.filename, b'', 'unsafe path in archive')
                    continue
                if info.file_size > MAX_MEMBER_BYTES:
                    yield (info.filename, b'', 'file too large')
                    continue
                with zf.open(info) as member:
                    # Read one byte past the cap so a lying header is caught.
                    data = member.read(MAX_MEMBER_BYTES + 1)
                if len(data) > MAX_MEMBER_BYTES:
                    yield (info.filename, b'', 'file too large')
                    continue
                total += len(data)
                if total > MAX_TOTAL_BYTES:
                    raise ArchiveRejected(
                        'archive expands past the '
                        f'{MAX_TOTAL_BYTES // (1024 * 1024)} MB limit')
                data, error = _gunzip(data, info.filename)
                yield (info.filename, data, error)
    except zipfile.BadZipFile as e:
        raise ArchiveRejected(f'unreadable archive: {e}') from e


def _read_capped_file(path: str) -> Tuple[bytes, str]:
    if os.path.getsize(path) > MAX_MEMBER_BYTES:
        return b'', 'file too large'
    with open(path, 'rb') as f:
        return f.read(), ''


def _gunzip(data: bytes, name: str) -> Tuple[bytes, str]:
    """Decompress a `.gz` member, capped. Non-gz data passes through.

    A bad member is a per-file error, not an archive-level one: a Strava export
    with one truncated `.fit.gz` must still import the other 811 files.
    """
    if not name.lower().endswith('.gz') or not data:
        return data, ''
    try:
        with gzip.GzipFile(fileobj=BytesIO(data)) as gz:
            out = gz.read(MAX_MEMBER_BYTES + 1)
    except (OSError, EOFError) as e:  # BadGzipFile and truncation
        return b'', f'unreadable gzip: {e}'
    if len(out) > MAX_MEMBER_BYTES:
        return b'', 'file too large'
    return out, ''  

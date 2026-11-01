from pathlib import Path

import gpxpy


def parse_gpx_file(filepath: str | Path) -> dict[str, list]:
    """Parse a GPX file and extract latitude, longitude, elevation, time data, and waypoints.

    Args:
        filepath: Path to the GPX file.

    Returns:
        Dictionary with lists of latitudes, longitudes, elevations, times, and waypoints.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ValueError: If file is not a GPX file.
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f'GPX file does not exist: {filepath}')

    if filepath.suffix.lower() != '.gpx':
        raise ValueError(f'Expected a .gpx file, got: {filepath.name}')

    with open(filepath, 'r', encoding='utf-8') as gpx_file:
        gpx = gpxpy.parse(gpx_file)

    latitudes: list[float] = []
    longitudes: list[float] = []
    elevations: list[float | None] = []
    times: list[str | None] = []

    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                latitudes.append(point.latitude)
                longitudes.append(point.longitude)
                elevations.append(point.elevation)
                times.append(point.time.isoformat() if point.time else None)

    waypoints: list[dict] = []
    for wpt in gpx.waypoints:
        waypoints.append({
            'lat': wpt.latitude,
            'lon': wpt.longitude,
            'name': wpt.name or '',
            'description': wpt.description or '',
            'symbol': wpt.symbol or '',
            'type': wpt.type or '',
        })

    return {
        'latitudes': latitudes,
        'longitudes': longitudes,
        'elevations': elevations,
        'times': times,
        'waypoints': waypoints,
    }

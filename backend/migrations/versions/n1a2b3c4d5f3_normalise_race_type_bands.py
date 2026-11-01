"""normalise UTMB World Series distance bands in races.race_type

Revision ID: n1a2b3c4d5f3
Revises: m1a2b3c4d5f2
Create Date: 2026-08-21 06:40:00.000000

``races.race_type`` is documented as ``road|trail|ultra|vertical`` but the UTMB
scraper was writing the World Series *distance band* (``ws20KM``, ``ws50KM``,
``ws100KM``, ``ws50M``, ``ws100M``) straight into it. Those rows rendered a raw
i18n key in the UI, were unreachable through the race-type filter, and scored
as an unknown category in ``_score_race``.

Ingestion is fixed in scripts/scrape_utmb.py + scripts/seed_races.py; this
backfills the rows already in the table.

Idempotent: matches only the band vocabulary, so a re-run finds nothing. Data
only — no schema change. ``external_id`` is deliberately left alone: it embeds
the band as part of an identity, and rewriting it would break upsert matching
and duplicate every band-fallback race.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'n1a2b3c4d5f3'
down_revision = 'm1a2b3c4d5f2'
branch_labels = None
depends_on = None


# Band → nominal km, used only where a race has no measured distance.
# Mirrors services/race_taxonomy.py; inlined because migrations must stay
# runnable against any past/future state of the application code.
BAND_NOMINAL_KM = {
    'ws20km': 20.0,
    'ws50km': 50.0,
    'ws100km': 100.0,
    'ws50m': 80.0,
    'ws100m': 161.0,
}
ULTRA_THRESHOLD_KM = 42.195


def _resolve(band: str, distance_km, surface) -> str:
    km = distance_km or BAND_NOMINAL_KM[band.lower()]
    if (surface or 'trail').strip().lower() in ('asphalt', 'road', 'track'):
        return 'road' if km < ULTRA_THRESHOLD_KM else 'ultra'
    return 'ultra' if km >= ULTRA_THRESHOLD_KM else 'trail'


def upgrade():
    conn = op.get_bind()
    if 'races' not in inspect(conn).get_table_names():
        return  # bare DB; init_db() materialises the table from the model

    rows = conn.execute(
        sa.text(
            "SELECT id, race_type, distance_km, surface FROM races "
            "WHERE lower(race_type) IN :bands"
        ).bindparams(sa.bindparam('bands', expanding=True)),
        {'bands': list(BAND_NOMINAL_KM)},
    ).fetchall()

    for race_id, band, distance_km, surface in rows:
        conn.execute(
            sa.text("UPDATE races SET race_type = :rt WHERE id = :id"),
            {'rt': _resolve(band, distance_km, surface), 'id': race_id},
        )


def downgrade():
    # The original band is not recoverable from the normalised value (several
    # bands collapse onto 'ultra'), and it carried no information that
    # distance_km does not already hold. Intentionally a no-op.
    pass

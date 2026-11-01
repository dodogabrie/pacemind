"""merge time_budget_prefs and route_cache heads

Revision ID: ed921de2e038
Revises: a1b2c3d4e5f6, g1a2b3c4d5e6
Create Date: 2026-04-30 19:54:05.256484

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ed921de2e038'
down_revision = ('a1b2c3d4e5f6', 'g1a2b3c4d5e6')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass

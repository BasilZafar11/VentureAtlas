"""Persist the per-user SerpApi allowance across restarts."""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('serpapi_user_budget',
                    sa.Column('subject', sa.String(72), primary_key=True),
                    sa.Column('day_ist', sa.String(10), primary_key=True),
                    sa.Column('calls_used', sa.Integer(), nullable=False))


def downgrade():
    op.drop_table('serpapi_user_budget')

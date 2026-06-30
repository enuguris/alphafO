"""add anthropic_api_key_enc to kite_config

Revision ID: d1e2f3a4b5c6
Revises: 70abe2b278ea
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3a4b5c6'
down_revision = 'c4d2e3f5a8b9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('kite_config',
        sa.Column('anthropic_api_key_enc', sa.String(), nullable=False, server_default='')
    )


def downgrade():
    op.drop_column('kite_config', 'anthropic_api_key_enc')

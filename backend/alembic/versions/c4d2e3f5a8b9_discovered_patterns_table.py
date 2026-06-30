"""discovered_patterns_table

Revision ID: c4d2e3f5a8b9
Revises: b3a1c4e5f6d7
Create Date: 2026-06-29 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d2e3f5a8b9'
down_revision = 'b3a1c4e5f6d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'discovered_patterns',
        sa.Column('id',           sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column('created_at',   sa.DateTime(), nullable=True),
        sa.Column('updated_at',   sa.DateTime(), nullable=True),
        sa.Column('underlying',   sa.String(32),  nullable=False),
        sa.Column('timeframe',    sa.String(10),  nullable=False),
        sa.Column('pattern_slug', sa.String(200), nullable=False),
        sa.Column('features',     sa.JSON(),      nullable=False),
        sa.Column('direction',    sa.String(8),   nullable=False),
        sa.Column('option_type',  sa.String(2),   nullable=False),
        sa.Column('n_samples',    sa.Integer(),   nullable=True),
        sa.Column('win_rate',     sa.Float(),     nullable=True),
        sa.Column('mean_fwd_ret', sa.Float(),     nullable=True),
        sa.Column('p_value',      sa.Float(),     nullable=True),
        sa.Column('effect_size',  sa.Float(),     nullable=True),
        sa.Column('source',       sa.String(20),  nullable=False),
        sa.Column('explanation',  sa.Text(),      nullable=False),
        sa.Column('active',       sa.Boolean(),   nullable=False, server_default='1'),
        sa.Column('last_backtest_win_rate',      sa.Float(),    nullable=True),
        sa.Column('last_backtest_profit_factor', sa.Float(),    nullable=True),
        sa.Column('last_backtest_trades',        sa.Integer(),  nullable=True),
        sa.Column('last_backtest_net_pnl',       sa.Float(),    nullable=True),
        sa.Column('last_backtest_at',            sa.DateTime(), nullable=True),
        sa.Column('has_edge',     sa.Boolean(),   nullable=False, server_default='0'),
    )
    op.create_index('ix_dp_underlying_tf',   'discovered_patterns', ['underlying', 'timeframe'])
    op.create_index('ix_dp_slug',            'discovered_patterns', ['pattern_slug'], unique=True)
    op.create_index('ix_dp_active_edge',     'discovered_patterns', ['active', 'has_edge'])


def downgrade() -> None:
    op.drop_table('discovered_patterns')

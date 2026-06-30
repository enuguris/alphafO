"""pattern_backtest_tables

Revision ID: b3a1c4e5f6d7
Revises: 70abe2b278ea
Create Date: 2026-06-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b3a1c4e5f6d7'
down_revision = '70abe2b278ea'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'pattern_backtests',
        sa.Column('id',              sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at',      sa.DateTime(), nullable=True),
        sa.Column('completed_at',    sa.DateTime(), nullable=True),
        sa.Column('underlying',      sa.String(32),  nullable=False),
        sa.Column('pattern_name',    sa.String(64),  nullable=False),
        sa.Column('timeframe',       sa.String(8),   nullable=False),
        sa.Column('date_from',       sa.String(10),  nullable=True),
        sa.Column('date_to',         sa.String(10),  nullable=True),
        sa.Column('bars_tested',     sa.Integer(),   nullable=True),
        sa.Column('total_signals',   sa.Integer(),   nullable=True),
        sa.Column('trades_taken',    sa.Integer(),   nullable=True),
        sa.Column('winning_trades',  sa.Integer(),   nullable=True),
        sa.Column('losing_trades',   sa.Integer(),   nullable=True),
        sa.Column('win_rate',        sa.Float(),     nullable=True),
        sa.Column('profit_factor',   sa.Float(),     nullable=True),
        sa.Column('avg_winner',      sa.Float(),     nullable=True),
        sa.Column('avg_loser',       sa.Float(),     nullable=True),
        sa.Column('total_net_pnl',   sa.Float(),     nullable=True),
        sa.Column('max_drawdown_pct',sa.Float(),     nullable=True),
        sa.Column('sharpe_ratio',    sa.Float(),     nullable=True),
        sa.Column('avg_holding_bars',sa.Float(),     nullable=True),
        sa.Column('status',          sa.String(16),  nullable=False, server_default='pending'),
        sa.Column('data_source',     sa.String(16),  nullable=True),
        sa.Column('error_message',   sa.Text(),      nullable=True),
    )
    op.create_index('ix_pb_underlying_pattern_tf', 'pattern_backtests',
                    ['underlying', 'pattern_name', 'timeframe'])
    op.create_index('ix_pb_status', 'pattern_backtests', ['status'])

    op.create_table(
        'pattern_trades',
        sa.Column('id',            sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('backtest_id',   sa.Integer(), sa.ForeignKey('pattern_backtests.id', ondelete='CASCADE'), nullable=False),
        sa.Column('underlying',    sa.String(32), nullable=False),
        sa.Column('pattern_name',  sa.String(64), nullable=False),
        sa.Column('timeframe',     sa.String(8),  nullable=True),
        sa.Column('signal_date',   sa.String(16), nullable=True),
        sa.Column('direction',     sa.String(8),  nullable=True),
        sa.Column('option_type',   sa.String(4),  nullable=True),
        sa.Column('strike',        sa.Float(),    nullable=True),
        sa.Column('expiry_dte',    sa.Integer(),  nullable=True),
        sa.Column('spot_at_entry', sa.Float(),    nullable=True),
        sa.Column('entry_price',   sa.Float(),    nullable=True),
        sa.Column('exit_price',    sa.Float(),    nullable=True),
        sa.Column('exit_reason',   sa.String(16), nullable=True),
        sa.Column('holding_bars',  sa.Integer(),  nullable=True),
        sa.Column('gross_pnl',     sa.Float(),    nullable=True),
        sa.Column('charges',       sa.Float(),    nullable=True),
        sa.Column('net_pnl',       sa.Float(),    nullable=True),
        sa.Column('pnl_pct',       sa.Float(),    nullable=True),
        sa.Column('iv_at_entry',   sa.Float(),    nullable=True),
        sa.Column('confidence',    sa.Float(),    nullable=True),
    )
    op.create_index('ix_pt_backtest_id', 'pattern_trades', ['backtest_id'])


def downgrade() -> None:
    op.drop_table('pattern_trades')
    op.drop_table('pattern_backtests')

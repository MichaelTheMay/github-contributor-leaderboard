"""Add scrape history tracking and fix reserved column names.

Creates scrape_windows table and adds scrape tracking fields to repositories.
Also renames 'metadata' columns to 'extra_data' (metadata is reserved in SQLAlchemy).

Revision ID: 001
Revises:
Create Date: 2026-02-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create scrape_windows table
    op.create_table(
        'scrape_windows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repository_id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=True),
        sa.Column('data_start_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('data_end_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('events_fetched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('contributors_found', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('bytes_processed', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('bytes_billed', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['job_id'], ['scrape_jobs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('repository_id', 'data_start_date', 'data_end_date', name='uq_scrape_windows_repo_date_range'),
    )
    op.create_index('idx_scrape_windows_repo_dates', 'scrape_windows', ['repository_id', 'data_end_date'])

    # Add scrape tracking columns to repositories table
    op.add_column('repositories', sa.Column('first_scraped_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('repositories', sa.Column('earliest_data_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('repositories', sa.Column('latest_data_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('repositories', sa.Column('never_rescrape_before', sa.DateTime(timezone=True), nullable=True))

    # Rename 'metadata' to 'extra_data' in cost_records and audit_logs
    # ('metadata' is a reserved name in SQLAlchemy's Declarative API)
    op.alter_column('cost_records', 'metadata', new_column_name='extra_data')
    op.alter_column('audit_logs', 'metadata', new_column_name='extra_data')


def downgrade() -> None:
    # Rename 'extra_data' back to 'metadata'
    op.alter_column('audit_logs', 'extra_data', new_column_name='metadata')
    op.alter_column('cost_records', 'extra_data', new_column_name='metadata')

    # Drop columns from repositories
    op.drop_column('repositories', 'never_rescrape_before')
    op.drop_column('repositories', 'latest_data_date')
    op.drop_column('repositories', 'earliest_data_date')
    op.drop_column('repositories', 'first_scraped_at')

    # Drop scrape_windows table
    op.drop_index('idx_scrape_windows_repo_dates', table_name='scrape_windows')
    op.drop_table('scrape_windows')

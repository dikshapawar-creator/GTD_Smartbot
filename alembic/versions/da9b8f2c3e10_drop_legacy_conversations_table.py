"""drop legacy conversations table

Revision ID: da9b8f2c3e10
Revises: ca7875da5a8f
Create Date: 2026-03-11 17:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'da9b8f2c3e10'
down_revision: Union[str, Sequence[str], None] = 'ca7875da5a8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table('conversations')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table('conversations',
    sa.Column('id', sa.dialects.mssql.UNIQUEIDENTIFIER(), nullable=False),
    sa.Column('lead_id', sa.dialects.mssql.UNIQUEIDENTIFIER(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('sender', sa.String(length=50), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], )
    )

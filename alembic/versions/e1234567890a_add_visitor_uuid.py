"""add visitor_uuid

Revision ID: e1234567890a
Revises: da9b8f2c3e10
Create Date: 2026-03-12 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import uuid


# revision identifiers, used by Alembic.
revision: str = 'e1234567890a'
down_revision: Union[str, Sequence[str], None] = 'c068a2ab690e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add column as nullable first to avoid errors on existing rows
    op.add_column('chat_sessions', sa.Column('visitor_uuid', sa.String(length=36), nullable=True))
    
    # Populate existing rows with a new UUID using SQL Server's NEWID() function
    op.execute("UPDATE chat_sessions SET visitor_uuid = CAST(NEWID() AS VARCHAR(36)) WHERE visitor_uuid IS NULL")
    
    # Alter column to be non-nullable as planned
    op.alter_column('chat_sessions', 'visitor_uuid',
               existing_type=sa.String(length=36),
               nullable=False)
               
    # Create the recommended index for fast history lookup
    op.create_index('ix_chat_sessions_visitor_uuid', 'chat_sessions', ['visitor_uuid'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_chat_sessions_visitor_uuid', table_name='chat_sessions')
    op.drop_column('chat_sessions', 'visitor_uuid')

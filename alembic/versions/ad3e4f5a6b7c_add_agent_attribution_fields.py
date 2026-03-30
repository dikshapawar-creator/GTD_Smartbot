"""add agent attribution fields

Revision ID: ad3e4f5a6b7c
Revises: c068a2ab690e
Create Date: 2026-03-30 14:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad3e4f5a6b7c'
down_revision: Union[str, Sequence[str], None] = 'c068a2ab690e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns to chat_messages
    op.add_column('chat_messages', sa.Column('sender_user_id', sa.Integer(), nullable=True))
    op.add_column('chat_messages', sa.Column('sender_name', sa.String(length=255), nullable=True))
    op.add_column('chat_messages', sa.Column('sender_email', sa.String(length=255), nullable=True))

    # Add columns to chat_sessions
    op.add_column('chat_sessions', sa.Column('assigned_agent_email', sa.String(length=255), nullable=True))
    op.add_column('chat_sessions', sa.Column('assigned_agent_name', sa.String(length=255), nullable=True))
    op.add_column('chat_sessions', sa.Column('agent_joined_at', sa.DateTime(), nullable=True))
    op.add_column('chat_sessions', sa.Column('closed_by_agent_id', sa.Integer(), nullable=True))
    op.add_column('chat_sessions', sa.Column('closed_by_agent_email', sa.String(length=255), nullable=True))
    op.add_column('chat_sessions', sa.Column('closed_by_agent_name', sa.String(length=255), nullable=True))
    op.add_column('chat_sessions', sa.Column('agent_closed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Remove columns from chat_sessions
    op.drop_column('chat_sessions', 'agent_closed_at')
    op.drop_column('chat_sessions', 'closed_by_agent_name')
    op.drop_column('chat_sessions', 'closed_by_agent_email')
    op.drop_column('chat_sessions', 'closed_by_agent_id')
    op.drop_column('chat_sessions', 'agent_joined_at')
    op.drop_column('chat_sessions', 'assigned_agent_name')
    op.drop_column('chat_sessions', 'assigned_agent_email')

    # Remove columns from chat_messages
    op.drop_column('chat_messages', 'sender_email')
    op.drop_column('chat_messages', 'sender_name')
    op.drop_column('chat_messages', 'sender_user_id')

"""enhance live chat models

Revision ID: f1234567890b
Revises: e1234567890a
Create Date: 2024-03-18 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql

# revision identifiers, used by Alembic.
revision = 'f1234567890b'
down_revision = 'e1234567890a'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to chat_sessions table
    try:
        op.add_column('chat_sessions', sa.Column('current_mode', sa.String(10), nullable=True))
        op.add_column('chat_sessions', sa.Column('agent_name', sa.String(255), nullable=True))
        op.add_column('chat_sessions', sa.Column('message_count', sa.Integer(), nullable=False, server_default='0'))
        op.add_column('chat_sessions', sa.Column('lead_name', sa.String(255), nullable=True))
        op.add_column('chat_sessions', sa.Column('lead_email', sa.String(255), nullable=True))
        op.add_column('chat_sessions', sa.Column('lead_phone', sa.String(50), nullable=True))
        op.add_column('chat_sessions', sa.Column('lead_company', sa.String(255), nullable=True))
        op.add_column('chat_sessions', sa.Column('ip_metadata', sa.Text(), nullable=True))
        op.add_column('chat_sessions', sa.Column('created_at', sa.DateTime(), nullable=True))
        op.add_column('chat_sessions', sa.Column('last_activity_at', sa.DateTime(), nullable=True))
        
        # Update existing records to have current_mode = conversation_mode
        op.execute("UPDATE chat_sessions SET current_mode = conversation_mode WHERE current_mode IS NULL")
        op.execute("UPDATE chat_sessions SET created_at = started_at_utc WHERE created_at IS NULL")
        op.execute("UPDATE chat_sessions SET last_activity_at = last_activity_utc WHERE last_activity_at IS NULL")
        
        # Make current_mode NOT NULL after populating
        op.alter_column('chat_sessions', 'current_mode', nullable=False)
        op.alter_column('chat_sessions', 'created_at', nullable=False)
        op.alter_column('chat_sessions', 'last_activity_at', nullable=False)
        
    except Exception as e:
        print(f"Migration warning: {e}")
        # Continue with migration even if some columns already exist
        pass

    # Add new columns to chat_messages table
    try:
        op.add_column('chat_messages', sa.Column('session_uuid', sa.String(64), nullable=True))
        op.add_column('chat_messages', sa.Column('created_at', sa.DateTime(), nullable=True))
        
        # Update existing records
        op.execute("""
            UPDATE chat_messages 
            SET created_at = created_at_utc 
            WHERE created_at IS NULL
        """)
        
        # Make created_at NOT NULL after populating
        op.alter_column('chat_messages', 'created_at', nullable=False)
        
        # Create index on session_uuid
        op.create_index('ix_chat_messages_session_uuid', 'chat_messages', ['session_uuid'])
        
    except Exception as e:
        print(f"Migration warning: {e}")
        # Continue with migration even if some columns already exist
        pass


def downgrade():
    # Remove added columns
    try:
        op.drop_column('chat_sessions', 'current_mode')
        op.drop_column('chat_sessions', 'agent_name')
        op.drop_column('chat_sessions', 'message_count')
        op.drop_column('chat_sessions', 'lead_name')
        op.drop_column('chat_sessions', 'lead_email')
        op.drop_column('chat_sessions', 'lead_phone')
        op.drop_column('chat_sessions', 'lead_company')
        op.drop_column('chat_sessions', 'ip_metadata')
        op.drop_column('chat_sessions', 'created_at')
        op.drop_column('chat_sessions', 'last_activity_at')
    except Exception as e:
        print(f"Downgrade warning: {e}")
        pass
    
    try:
        op.drop_index('ix_chat_messages_session_uuid', 'chat_messages')
        op.drop_column('chat_messages', 'session_uuid')
        op.drop_column('chat_messages', 'created_at')
    except Exception as e:
        print(f"Downgrade warning: {e}")
        pass
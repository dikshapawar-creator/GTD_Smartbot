"""Add user_tenants table and is_super_admin to users

Revision ID: a1b2c3d4e5f6
Revises: (latest)
Create Date: 2026-03-25

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f1234567890b'  # latest head: enhance_live_chat_models
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add is_super_admin column to users table (non-breaking, default=0)
    op.add_column(
        'users',
        sa.Column('is_super_admin', sa.Boolean(), nullable=False, server_default=sa.text('0'))
    )

    # 2. Create user_tenants table
    op.create_table(
        'user_tenants',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('GETDATE()')),
        sa.UniqueConstraint('user_id', 'tenant_id', name='uq_user_tenant'),
    )
    op.create_index('ix_user_tenants_user_id', 'user_tenants', ['user_id'])
    op.create_index('ix_user_tenants_tenant_id', 'user_tenants', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_user_tenants_tenant_id', table_name='user_tenants')
    op.drop_index('ix_user_tenants_user_id', table_name='user_tenants')
    op.drop_table('user_tenants')
    op.drop_column('users', 'is_super_admin')

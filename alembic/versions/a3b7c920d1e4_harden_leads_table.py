"""Harden leads table — NOT NULL, UNIQUE, indexes, new columns

Revision ID: a3b7c920d1e4
Revises: 80f29f04e7d6
Create Date: 2026-02-20 15:10:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a3b7c920d1e4'
down_revision = '80f29f04e7d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Enterprise hardening for leads table:
      1. Backfill NULLs so NOT NULL constraints can be applied
      2. Alter columns to NOT NULL
      3. Add new metadata columns (source, ip_address, country, city, updated_at)
      4. Add UNIQUE constraint on email
      5. Add indexes on status and created_at
    """
    # ── Step 1: Backfill NULLs ───────────────────────────────────────────
    op.execute(
        "UPDATE leads SET name = 'Unknown' WHERE name IS NULL"
    )
    op.execute(
        "UPDATE leads SET email = CONCAT('unknown_', CAST(id AS VARCHAR(36)), '@placeholder.invalid') WHERE email IS NULL"
    )
    op.execute(
        "UPDATE leads SET company = 'Unknown' WHERE company IS NULL"
    )
    op.execute(
        "UPDATE leads SET phone = '+000000000000' WHERE phone IS NULL"
    )
    op.execute(
        "UPDATE leads SET status = 'NEW' WHERE status IS NULL"
    )

    # ── Step 2: Add new columns ──────────────────────────────────────────
    op.add_column('leads', sa.Column('source', sa.String(50), nullable=False, server_default='chatbot_form'))
    op.add_column('leads', sa.Column('ip_address', sa.String(45), nullable=True))
    op.add_column('leads', sa.Column('country', sa.String(100), nullable=True))
    op.add_column('leads', sa.Column('city', sa.String(100), nullable=True))
    op.add_column('leads', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

    # ── Step 3: Alter columns to NOT NULL ────────────────────────────────
    op.alter_column('leads', 'name', existing_type=sa.String(255),
                    type_=sa.String(100), nullable=False)
    op.alter_column('leads', 'email', existing_type=sa.String(255),
                    nullable=False)
    op.alter_column('leads', 'company', existing_type=sa.String(255),
                    type_=sa.String(150), nullable=False)
    op.alter_column('leads', 'phone', existing_type=sa.String(50),
                    type_=sa.String(20), nullable=False)
    op.alter_column('leads', 'status', existing_type=sa.String(50),
                    type_=sa.String(20), nullable=False,
                    server_default='NEW')

    # ── Step 4: UNIQUE constraint on email ───────────────────────────────
    op.create_unique_constraint('uq_leads_email', 'leads', ['email'])

    # ── Step 5: Indexes ──────────────────────────────────────────────────
    op.create_index('ix_leads_status', 'leads', ['status'])
    op.create_index('ix_leads_created_at', 'leads', ['created_at'])


def downgrade() -> None:
    """Reverse the hardening — drop constraints, columns, revert nullability."""
    op.drop_index('ix_leads_created_at', table_name='leads')
    op.drop_index('ix_leads_status', table_name='leads')
    op.drop_constraint('uq_leads_email', 'leads', type_='unique')

    op.alter_column('leads', 'status', existing_type=sa.String(20),
                    type_=sa.String(50), nullable=True, server_default=None)
    op.alter_column('leads', 'phone', existing_type=sa.String(20),
                    type_=sa.String(50), nullable=True)
    op.alter_column('leads', 'company', existing_type=sa.String(150),
                    type_=sa.String(255), nullable=True)
    op.alter_column('leads', 'email', existing_type=sa.String(255),
                    nullable=True)
    op.alter_column('leads', 'name', existing_type=sa.String(100),
                    type_=sa.String(255), nullable=True)

    op.drop_column('leads', 'updated_at')
    op.drop_column('leads', 'city')
    op.drop_column('leads', 'country')
    op.drop_column('leads', 'ip_address')
    op.drop_column('leads', 'source')

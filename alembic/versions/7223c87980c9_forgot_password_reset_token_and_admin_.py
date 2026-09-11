"""forgot-password reset token columns, plus a one-time admin bootstrap upsert

Revision ID: 7223c87980c9
Revises: ce94da2fa07f
Create Date: 2026-09-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import table, column
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7223c87980c9'
down_revision: Union[str, None] = 'ce94da2fa07f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('reset_token_hash', sa.String(), nullable=True))
    op.add_column('users', sa.Column('reset_token_expires_at', sa.DateTime(timezone=True), nullable=True))

    # One-time convenience seed: if ADMIN_BOOTSTRAP_EMAIL/ADMIN_BOOTSTRAP_PASSWORD
    # are set in the deploy environment, upsert that login so there's always a
    # working admin account before forgot-password is in real use. No-op (and
    # safe to leave in migration history) once both are unset.
    from app.auth import hash_password
    from app.config import settings

    if settings.admin_bootstrap_email and settings.admin_bootstrap_password:
        conn = op.get_bind()
        users = table(
            'users',
            column('id', postgresql.UUID(as_uuid=True)),
            column('email', sa.String),
            column('password_hash', sa.String),
            column('role', sa.String),
        )
        password_hash = hash_password(settings.admin_bootstrap_password)
        existing = conn.execute(
            sa.select(users.c.id).where(users.c.email == settings.admin_bootstrap_email)
        ).first()
        if existing:
            conn.execute(
                users.update()
                .where(users.c.id == existing.id)
                .values(password_hash=password_hash)
            )
        else:
            import uuid
            conn.execute(
                users.insert().values(
                    id=uuid.uuid4(),
                    email=settings.admin_bootstrap_email,
                    password_hash=password_hash,
                    role='ADMIN',
                )
            )


def downgrade() -> None:
    op.drop_column('users', 'reset_token_expires_at')
    op.drop_column('users', 'reset_token_hash')

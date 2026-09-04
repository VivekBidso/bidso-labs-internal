"""stage attachment metadata + nullable uploaded_by

Revision ID: a1b2c3d4e5f6
Revises: ee6e6a0923fa
Create Date: 2026-09-04

"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "ee6e6a0923fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("stage_attachments", "uploaded_by", nullable=True)
    op.add_column("stage_attachments", sa.Column("original_filename", sa.String(), nullable=True))
    op.add_column("stage_attachments", sa.Column("content_type", sa.String(), nullable=True))
    op.add_column("stage_attachments", sa.Column("size_bytes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("stage_attachments", "size_bytes")
    op.drop_column("stage_attachments", "content_type")
    op.drop_column("stage_attachments", "original_filename")
    op.alter_column("stage_attachments", "uploaded_by", nullable=False)

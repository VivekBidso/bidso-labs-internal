"""detailed score sheet rationale field

Revision ID: 0463765120ad
Revises: 7223c87980c9
Create Date: 2026-09-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0463765120ad'
down_revision: Union[str, None] = '7223c87980c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'detailed_score_sheets',
        sa.Column('rationale', sa.Text(), nullable=False, server_default=''),
    )
    op.alter_column('detailed_score_sheets', 'rationale', server_default=None)


def downgrade() -> None:
    op.drop_column('detailed_score_sheets', 'rationale')

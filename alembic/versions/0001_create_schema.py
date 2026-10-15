"""create resume_forge schema

Revision ID: 0001
Revises:
Create Date: 2026-10-14 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('CREATE SCHEMA IF NOT EXISTS resume_forge')


def downgrade() -> None:
    """Downgrade schema."""
    op.execute('DROP SCHEMA IF EXISTS resume_forge')

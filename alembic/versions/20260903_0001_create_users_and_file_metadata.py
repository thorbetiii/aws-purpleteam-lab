"""Create users and file metadata tables.

Revision ID: 20260903_0001
Revises:
Create Date: 2026-09-03

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "20260903_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the initial application tables and lookup index."""
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.String(length=32),
            server_default=sa.text("'user'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'admin')",
            name="ck_users_role_allowed",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "file_metadata",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("s3_object_key", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name="ck_file_metadata_size_bytes_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_file_metadata_owner_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file_metadata")),
        sa.UniqueConstraint(
            "s3_object_key",
            name=op.f("uq_file_metadata_s3_object_key"),
        ),
    )
    op.create_index(
        op.f("ix_file_metadata_owner_id"),
        "file_metadata",
        ["owner_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the initial application tables in dependency order."""
    op.drop_index(
        op.f("ix_file_metadata_owner_id"),
        table_name="file_metadata",
    )
    op.drop_table("file_metadata")
    op.drop_table("users")

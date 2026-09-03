"""Shared SQLAlchemy declarative base for application database models."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Stable names make future Alembic migrations and PostgreSQL constraints easier
# to inspect, review, and reproduce across environments.
CONSTRAINT_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class that all SQLAlchemy ORM models will inherit from."""

    metadata = MetaData(naming_convention=CONSTRAINT_NAMING_CONVENTION)

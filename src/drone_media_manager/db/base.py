"""SQLAlchemy declarative base for control-plane persistence."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class shared by all database models."""

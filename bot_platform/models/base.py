"""Bazowy obiekt deklaratywny SQLAlchemy."""
from __future__ import annotations

from sqlalchemy.orm import declarative_base

Base = declarative_base()

__all__ = ["Base"]

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    """Base class for future SQLAlchemy ORM models."""

    pass


# `pool_pre_ping` verifies a pooled RDS connection before it is reused.
engine = create_engine(get_settings().database_url, pool_pre_ping=True)
# Each request receives its own session from this factory.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and always close it after the request completes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

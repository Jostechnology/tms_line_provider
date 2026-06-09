import os
from sqlalchemy import create_engine, Column, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class LineOAToken(Base):
    """Each row is one LINE OA registration. token is the primary key."""
    __tablename__ = "line_oa_tokens"

    token                = Column(String, primary_key=True, index=True)
    company_id           = Column(String, nullable=False, index=True)
    channel_secret       = Column(String, nullable=False)
    channel_access_token = Column(String, nullable=False)
    created_at           = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at           = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                                  onupdate=lambda: datetime.now(timezone.utc))


def init_db():
    """Create tables if they don't exist. Call once at app startup."""
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

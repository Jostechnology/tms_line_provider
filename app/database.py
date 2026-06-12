import os
from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Integer, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class LineOAToken(Base):
    """Each row is one LINE OA registration. token is the primary key."""
    __tablename__ = "line_oa_tokens"

    token                = Column(String(64), primary_key=True, index=True)
    company_id           = Column(String(64), nullable=False, index=True)
    channel_secret       = Column(String(64), nullable=False)
    channel_access_token = Column(String(512), nullable=False)
    created_at           = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at           = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                                  onupdate=lambda: datetime.now(timezone.utc))


class RecipientLink(Base):
    """
    Links a customer_code to a LINE userId within a tenant.
    oa_token references the LineOAToken the user registered through —
    notifications are pushed back out via that same OA.
    """
    __tablename__ = "recipient_links"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    company_id    = Column(String(64), nullable=False, index=True)
    customer_code = Column(String(128), nullable=True, index=True)
    line_user_id  = Column(String(64), nullable=False, index=True)
    oa_token      = Column(String(64), nullable=True)
    tms_username  = Column(String(128), nullable=True)
    opted_in      = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))


class LineTmsLink(Base):
    """
    Maps a TMS user ID to a LINE user ID.
    Created when a user completes the LINE OAuth flow from TMS.
    This is the only table the OAuth flow writes to.
    """
    __tablename__ = "line_tms_links"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    tms_id     = Column(String(128), nullable=False, unique=True, index=True)
    line_id    = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class DeliveryLog(Base):
    """
    Every outbound LINE push attempt, one row per attempt.
    Captures event type, recipient, outcome, and any error detail.
    """
    __tablename__ = "delivery_logs"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    company_id    = Column(String(64), nullable=False, index=True)
    trip_id       = Column(String(128), nullable=False, index=True)
    event_type    = Column(String(64), nullable=False)
    customer_code = Column(String(128), nullable=False)
    line_user_id  = Column(String(64), nullable=True)
    status        = Column(String(32), nullable=False)
    error_detail  = Column(Text, nullable=True)
    occurred_at   = Column(DateTime(timezone=True), nullable=False)
    pushed_at     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def init_db():
    """Create tables if they don't exist. Call once at app startup."""
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

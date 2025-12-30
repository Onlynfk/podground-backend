import uuid
import json
from sqlalchemy.dialects.postgresql import ENUM, ARRAY, UUID as PostgreSQL_UUID
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    Text,
)
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.dialects.postgresql import UUID as PostgreSQL_UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from post_models import PodcastExperience, HeardAbout, PodcastChallenge, YesNo

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")


# Custom UUID type that works with both SQLite and PostgreSQL
class GUID(TypeDecorator):
    """Platform-independent GUID type.
    Uses PostgreSQL's UUID type, otherwise uses CHAR(36), storing as stringified hex values.
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PostgreSQL_UUID())
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            if not isinstance(value, uuid.UUID):
                return str(uuid.UUID(value))
            else:
                return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid.UUID):
                value = uuid.UUID(value)
            return value

engine = create_engine(
    DATABASE_URL,
    connect_args=(
        {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
    ),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class JsonEncodedList(TypeDecorator):
    """Encodes a Python list into a JSON string."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        # Convert list of enums to list of strings
        return json.dumps([item.value for item in value])

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        # Convert list of strings back to list of enums
        return [PodcastChallenge(item) for item in json.loads(value)]


# Conditional type for challenges column
if "postgresql" in DATABASE_URL:
    challenges_column_type = ARRAY(
        ENUM(PodcastChallenge, name="podcast_challenge", create_type=False)
    )
else:
    challenges_column_type = JsonEncodedList


class ABCounter(Base):
    __tablename__ = "ab_counter"

    id = Column(Integer, primary_key=True, index=True)
    count = Column(Integer, default=0)


class WaitlistEmail(Base):
    __tablename__ = "waitlist_emails"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    variant = Column(String, nullable=True)  # "A" or "B"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    sent_to_customerio = Column(Integer, default=0)  # 0=not sent, 1=sent


class MicrograntWaitlistEmail(Base):
    __tablename__ = "microgrant_waitlist_emails"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    sent_to_customerio = Column(Integer, default=0)  # 0=not sent, 1=sent


class PodcastCategory(Base):
    __tablename__ = "podcast_categories"

    id = Column(String, primary_key=True, index=True)  # UUID from Supabase
    category_name = Column(String, nullable=False, unique=True)
    apple_podcast_url = Column(String, nullable=False)
    active = Column(Boolean, default=True, nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_revoked = Column(Boolean, default=False, nullable=False)
    user_agent = Column(String, nullable=True)  # Track device/browser
    ip_address = Column(String, nullable=True)  # Track location


class UserOnboardingCategories(Base):
    __tablename__ = "user_onboarding_categories"

    id = Column(String, primary_key=True, index=True)  # UUID from Supabase
    user_id = Column(String, nullable=False, index=True)  # UUID from Supabase
    category_id = Column(
        String, ForeignKey("podcast_categories.id"), nullable=False
    )  # UUID from Supabase
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationship to PodcastCategory
    category = relationship("PodcastCategory")


class GrantApplications(Base):
    __tablename__ = "grant_applications"

    id = Column(GUID, primary_key=True, default=lambda: uuid.uuid4())
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    podcast_title = Column(String, nullable=False, unique=True)
    podcast_link = Column(String, nullable=False, unique=True)
    podcasting_experience = Column(
        ENUM(PodcastExperience, name="podcast_experience", create_type=False),
        nullable=False,
    )
    why_started = Column(Text, nullable=False)
    challenges = Column(
        challenges_column_type,
        nullable=False,
    )
    other_challenge_text = Column(Text, nullable=True)
    biggest_challenge = Column(Text, nullable=False)
    goals_next_year = Column(Text, nullable=False)
    steps_to_achieve = Column(String, nullable=False)
    proud_episode_link = Column(String, nullable=True)
    willing_to_share_public = Column(
        ENUM(YesNo, name="yes_no", create_type=False), nullable=False
    )
    heard_about = Column(
        ENUM(HeardAbout, name="heard_about", create_type=False), nullable=False
    )
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_ab_counter():
    """Initialize AB counter if it doesn't exist"""
    db = SessionLocal()
    try:
        counter = db.query(ABCounter).first()
        if not counter:
            counter = ABCounter(count=0)
            db.add(counter)
            db.commit()
    finally:
        db.close()

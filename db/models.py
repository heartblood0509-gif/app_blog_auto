"""SQLAlchemy 데이터 모델"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, unique=True, nullable=False)
    profile_path = Column(String)  # Chrome user data dir
    platform = Column(String, default="blog")  # blog, cafe, both
    cafe_club_id = Column(String, nullable=True)
    cafe_menu_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime, nullable=True)
    last_post_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())


class Post(Base):
    __tablename__ = "posts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(String, nullable=True)
    keyword = Column(String, nullable=False)
    title = Column(String)
    content_md = Column(Text)
    image_paths = Column(JSON, default=list)
    platform = Column(String, default="blog")  # blog, cafe
    status = Column(String, default="draft")  # draft, queued, publishing, published, failed
    publish_mode = Column(String, default="immediate")  # immediate, scheduled, draft
    scheduled_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    published_url = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    template_id = Column(String, nullable=True)
    reference_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())


class PostLog(Base):
    __tablename__ = "post_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(String, nullable=True)
    level = Column(String, default="info")  # info, warning, error
    message = Column(Text)
    created_at = Column(DateTime, default=func.now())

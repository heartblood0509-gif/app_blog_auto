"""SQLAlchemy 데이터베이스 초기화"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from config import settings
from db.models import Base


def get_engine():
    db_path = settings.DB_PATH
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_db():
    """데이터베이스 및 테이블 생성"""
    engine = get_engine()
    Base.metadata.create_all(engine)
    return engine


def get_session() -> Session:
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()

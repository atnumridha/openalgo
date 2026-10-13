"""Owner partitioned execution facts, using native engine/session lifecycle."""

from sqlalchemy import Column, String, JSON
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker
from database.engine_factory import create_db_engine

engine = create_db_engine()
db_session = scoped_session(sessionmaker(bind=engine))
Base = declarative_base()


class NeoFill(Base):
    __tablename__ = "neo_recorded_fill"
    owner = Column(String(100), primary_key=True)
    identity = Column(String(64), primary_key=True)
    payload = Column(JSON, nullable=False)


def init_db():
    Base.metadata.create_all(engine)


class NeoResearchJob(Base):
    __tablename__ = "neo_research_job"
    id = Column(String(64), primary_key=True)
    owner = Column(String(100), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    request = Column(JSON, nullable=False)
    result = Column(JSON)
    error = Column(String(500))

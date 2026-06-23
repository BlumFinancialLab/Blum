from contextlib import contextmanager
from datetime import datetime
import time

from sqlalchemy import event
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@event.listens_for(engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("blum_query_start_time", []).append(time.perf_counter())
    conn.info.setdefault("blum_query_wall_start_time", []).append(datetime.utcnow())


@event.listens_for(engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    start_stack = conn.info.get("blum_query_start_time", [])
    wall_stack = conn.info.get("blum_query_wall_start_time", [])
    started = start_stack.pop() if start_stack else time.perf_counter()
    wall_started = wall_stack.pop() if wall_stack else datetime.utcnow()
    duration_ms = (time.perf_counter() - started) * 1000
    try:
        from app.services.performance import performance_recorder

        performance_recorder.record_db_query(
            statement=statement,
            duration_ms=duration_ms,
            rowcount=getattr(cursor, "rowcount", None),
            started_at=wall_started,
            parameters=parameters,
        )
    except Exception:
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

"""Record each background job's runs in job_runs, so /api/status can show their health."""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.pipeline.pricing import utcnow

log = logging.getLogger(__name__)


@contextmanager
def recorded(session: Session, name: str) -> Iterator[dict]:
    """Wrap a job run. The job fills the yielded dict; it is saved as the run's detail."""
    run = session.get(JobRun, name) or JobRun(name=name)
    run.started_at, run.finished_at, run.ok = utcnow(), None, None
    session.add(run)
    session.commit()
    detail: dict = {}
    try:
        yield detail
    except Exception as exc:
        session.rollback()
        run = session.get(JobRun, name) or JobRun(name=name)
        run.ok, run.finished_at = False, utcnow()
        run.detail = f"{exc.__class__.__name__}: {exc}"
        session.add(run)
        session.commit()
        log.exception("job %s failed", name)
        raise
    run = session.get(JobRun, name) or JobRun(name=name)
    run.ok, run.finished_at = True, utcnow()
    run.detail = json.dumps(detail, default=str)
    session.add(run)
    session.commit()


def get_cursor(session: Session, name: str) -> str | None:
    run = session.get(JobRun, name)
    return run.cursor if run else None


def set_cursor(session: Session, name: str, value: str) -> None:
    run = session.get(JobRun, name) or JobRun(name=name)
    run.cursor = value
    session.add(run)
    session.commit()

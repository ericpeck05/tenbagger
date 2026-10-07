import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import portfolio, search, status, stock, watchlist
from app.db.models import Base
from app.db.session import get_engine
from app.jobs import scheduler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s %(message)s")
    for noisy in ("httpx", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    Base.metadata.create_all(get_engine())
    jobs = scheduler.start()
    yield
    if jobs is not None:
        jobs.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="Tenbagger", version=__version__, lifespan=lifespan)
    for module in (status, stock, search, watchlist, portfolio):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()

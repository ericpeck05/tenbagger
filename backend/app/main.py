from fastapi import FastAPI

from app import __version__
from app.api import status


def create_app() -> FastAPI:
    app = FastAPI(title="Tenbagger", version=__version__)
    app.include_router(status.router, prefix="/api")
    return app


app = create_app()

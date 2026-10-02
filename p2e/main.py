"""FastAPI app factory.  Run:  .venv\\Scripts\\python -m uvicorn p2e.main:app --port 8000"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.status import HTTP_422_UNPROCESSABLE_CONTENT

from p2e import __version__
from p2e.api.agent import router as agent_router
from p2e.api.auth import parse_api_keys
from p2e.api.documents import router as documents_router
from p2e.api.links import router as links_router
from p2e.api.review import router as review_router
from p2e.api.routes import health_router, router
from p2e.config import get_settings
from p2e.db.session import make_engine, make_sessionmaker
from p2e.extract.pipeline import load_project_vocab
from p2e.link import adjudicate

PROBLEM = "application/problem+json"
TITLES = {401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 409: "Conflict", 413: "Content Too Large",
          415: "Unsupported Media Type", 422: "Invalid request", 500: "Internal Server Error", 503: "Service Unavailable"}


def create_app(db_url: str | None = None, *, api_keys: dict[str, str] | None = None, upload_dir: Path | None = None,
               glossary_path: Path | None = None, llm=None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="P2E Bridge API (SIH26122)", version=__version__)
    app.state.engine = make_engine(db_url or settings.db_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.state.api_keys = api_keys if api_keys is not None else parse_api_keys(settings.api_keys_spec)
    app.state.upload_dir = Path(upload_dir or settings.upload_dir)
    app.state.glossary_path = Path(glossary_path or settings.glossary_path)
    app.state.vocab = load_project_vocab(app.state.glossary_path)
    app.state.llm = llm if llm is not None else adjudicate.from_env()   # None unless P2E_LLM_ENDPOINT is set
    app.include_router(health_router)
    app.include_router(router)
    app.include_router(documents_router)
    app.include_router(links_router)
    app.include_router(agent_router)
    app.include_router(review_router)

    @app.exception_handler(StarletteHTTPException)
    async def http_problem(_: Request, exc: StarletteHTTPException):
        return JSONResponse({"type": "about:blank", "title": TITLES.get(exc.status_code, "Error"), "status": exc.status_code,
                             "detail": exc.detail}, status_code=exc.status_code, media_type=PROBLEM, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_problem(_: Request, exc: RequestValidationError):
        detail = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse({"type": "about:blank", "title": "Invalid request", "status": 422, "detail": detail},
                            status_code=HTTP_422_UNPROCESSABLE_CONTENT, media_type=PROBLEM)

    return app


app = create_app()

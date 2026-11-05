import html
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from .core import CORS_ORIGINS, ApiError, SessionLocal, engine
from .models import Base
from .routers import api, pages

Base.metadata.create_all(engine)
if os.getenv("AUTO_SEED") == "1":
    from . import seed
    seed.run()

app = FastAPI(title="Medical Navigator API", version="1.0.0")
if CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])


def err(status, code, msg, details=None):
    return JSONResponse({"error": {"code": code, "message": msg, "details": details or {}}}, status_code=status)


@app.exception_handler(ApiError)
async def _api_error(request: Request, e: ApiError):
    if request.url.path.startswith("/api"):
        return err(e.status, e.code, e.message, e.details)
    if e.status == 401:
        return RedirectResponse("/login.html", 303)
    return HTMLResponse(f'<meta charset="utf-8"><link rel="stylesheet" href="/css/app.css"><main class="wrap">'
                        f'<h1>{e.status}</h1><p>{html.escape(e.message)}</p><a href="/">На главную</a></main>', e.status)


@app.exception_handler(RequestValidationError)
async def _validation(request: Request, e: RequestValidationError):
    return err(422, "VALIDATION_ERROR", "Неверные данные запроса",
               {"errors": [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()]})


@app.exception_handler(StarletteHTTPException)
async def _http(request: Request, e: StarletteHTTPException):
    if request.url.path.startswith("/api"):
        return err(e.status_code, {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(e.status_code, "HTTP_ERROR"), str(e.detail))
    return await http_exception_handler(request, e)


@app.get("/health")
def health():
    with SessionLocal() as db:
        db.execute(text("select 1"))
    return {"status": "ok"}


app.include_router(api.r)
app.include_router(pages.pages)
app.mount("/", StaticFiles(directory=str(Path(__file__).resolve().parents[2] / "frontend"), html=True), name="web")

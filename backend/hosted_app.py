import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if host:
    os.environ.setdefault("TONCONNECT_EXPECTED_DOMAIN", host)

from main import app as api

PUBLIC_URL = os.environ.get("RENDER_EXTERNAL_URL", "http://127.0.0.1:10000").rstrip("/")
STATIC = Path(os.environ.get("TON_TRACKER_STATIC_DIR", Path(__file__).resolve().parents[1] / "frontend/dist"))


@asynccontextmanager
async def lifespan(app):
    async with api.router.lifespan_context(api):
        yield


app = FastAPI(lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None)


@app.get("/", include_in_schema=False)
def homepage():
    return FileResponse(STATIC / "index.html")


@app.get("/tonconnect-manifest.json", include_in_schema=False)
def manifest():
    return {"url": PUBLIC_URL, "name": "GRAM Scope", "iconUrl": PUBLIC_URL + "/gram-scope-icon.png"}


@app.get("/gram-scope-icon.png", include_in_schema=False)
def icon():
    return FileResponse(STATIC / "gram-scope-icon.png")


app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")
app.mount("/", api)

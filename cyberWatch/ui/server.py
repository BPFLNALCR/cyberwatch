"""FastAPI UI server serving Jinja templates and static assets."""
from __future__ import annotations

import os
from typing import Any, Dict

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

API_BASE = os.getenv("CYBERWATCH_API_BASE", "http://localhost:8000")

app = FastAPI(title="cyberWatch-ui", version="0.1.0")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

_session: aiohttp.ClientSession | None = None


@app.on_event("startup")
async def startup_event() -> None:
    global _session
    if _session is None:
        _session = aiohttp.ClientSession()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _session
    if _session is not None:
        await _session.close()
        _session = None


def _ctx(request: Request, **kwargs: Any) -> Dict[str, Any]:
    base = {"request": request, "api_base": API_BASE}
    base.update(kwargs)
    return base


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", _ctx(request))


@app.get("/traceroute", response_class=HTMLResponse)
async def traceroute_page(request: Request):
    return templates.TemplateResponse("traceroute.html", _ctx(request))


@app.get("/asn", response_class=HTMLResponse)
async def asn_page(request: Request):
    return templates.TemplateResponse("asn.html", _ctx(request))


@app.get("/graph", response_class=HTMLResponse)
async def graph_page(request: Request):
    return templates.TemplateResponse("graph.html", _ctx(request))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "cyberWatch.ui.server:app",
        host=os.getenv("CYBERWATCH_UI_HOST", "0.0.0.0"),
        port=int(os.getenv("CYBERWATCH_UI_PORT", "8080")),
        reload=bool(os.getenv("CYBERWATCH_UI_RELOAD", "")),
    )

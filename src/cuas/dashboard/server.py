"""The dashboard server: the WebSocket stream and HTTP API of docs/dashboard_contract.md.

A ``Hub`` holds the one current run, the latest frame and the connected clients. Runs come from
a ``Launcher`` the composition root supplies (``scripts/run_demo.py``), because the dashboard may
not start the simulator itself. Everything is served locally; the API documentation pages are
turned off because they load their assets from a CDN.

Mount paths: the API under ``/api``, the stream at ``/ws``, the reference page at ``/reference/``,
and the operator dashboard from ``static/app/`` at ``/``. Until that exists, ``/`` redirects to
the reference page.
"""

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from cuas.clock import SimClock
from cuas.dashboard.contract import (
    EvidenceEvent,
    Frame,
    Hello,
    RunControl,
    RunInfo,
    SiteProfile,
    StartRun,
    contract_schema,
)

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
REFERENCE_DIR = STATIC / "reference"
APP_DIR = STATIC / "app"
CLIP_ID = re.compile(r"^[0-9a-f]{16}$")
CLIP_SUFFIX = ".mp4"

Outgoing = Hello | RunInfo | Frame | EvidenceEvent
Publish = Callable[[Outgoing], None]


@dataclass
class Started:
    """What a launcher hands back: the run, its clock, where its recordings are, its task."""

    run: RunInfo
    clock: SimClock
    real_time_pace: float
    """The clock's pace at speed 1."""
    clips_dir: Path | None
    done: asyncio.Task[None]


class Launcher(Protocol):
    def profiles(self) -> list[SiteProfile]: ...

    async def start(self, request: StartRun, publish: Publish) -> Started:
        """Start a run. Raises ``LookupError`` for a profile or scenario it does not have."""
        ...


class Busy(Exception):
    """A run is already going."""


class _Client:
    """One connection's outbox. Frames are snapshots, so a slow client only gets the latest."""

    def __init__(self) -> None:
        self._pending: list[tuple[str, str]] = []
        self._ready = asyncio.Event()

    def put(self, kind: str, text: str) -> None:
        if kind == "frame":
            self._pending = [p for p in self._pending if p[0] != "frame"]
        self._pending.append((kind, text))
        self._ready.set()

    async def take(self) -> list[str]:
        await self._ready.wait()
        self._ready.clear()
        out, self._pending = self._pending, []
        return [text for _, text in out]


class Hub:
    def __init__(self, launcher: Launcher) -> None:
        self._launcher = launcher
        self.profiles = launcher.profiles()
        self.run: RunInfo | None = None
        self.frame: Frame | None = None
        self._started: Started | None = None
        self._clients: set[_Client] = set()
        self._watcher: asyncio.Task[None] | None = None

    @property
    def active(self) -> bool:
        return self.run is not None and self.run.state != "ended"

    def hello(self) -> Hello:
        return Hello(profiles=self.profiles, run=self.run, frame=self.frame)

    async def start(self, request: StartRun) -> RunInfo:
        if self.active:
            raise Busy("a run is already going")
        started = await self._launcher.start(request, self.publish)
        self._started, self.frame = started, None
        self.publish(started.run)
        self._watcher = asyncio.create_task(self._end_when_done(started.done))
        return started.run

    def control(self, request: RunControl) -> RunInfo:
        if not self.active or self._started is None or self.run is None:
            raise LookupError("no run is going")
        clock = self._started.clock
        if request.action == "pause":
            clock.pause()
            run = self.run.model_copy(update={"state": "paused"})
        elif request.action == "play":
            clock.resume()
            run = self.run.model_copy(update={"state": "running"})
        else:
            speed = float(request.speed or 1)
            clock.set_pace(speed * self._started.real_time_pace)
            run = self.run.model_copy(update={"speed": speed})
        self.publish(run)
        return run

    def publish(self, message: Outgoing) -> None:
        if isinstance(message, RunInfo):
            self.run = message
        elif isinstance(message, Frame):
            self.frame = message
        text = message.model_dump_json()
        for client in self._clients:
            client.put(message.type, text)

    def clip(self, station_id: str, clip_id: str) -> Path | None:
        """A recording of the current run, if both IDs are real; never any other file."""
        if self.run is None or self._started is None or self._started.clips_dir is None:
            return None
        stations = {s.station_id for s in self.run.site.stations}
        if station_id not in stations or not CLIP_ID.match(clip_id):
            return None
        path = (
            self._started.clips_dir
            / f"station_{station_id}"
            / f"{clip_id}{CLIP_SUFFIX}"
        )
        return path if path.is_file() else None

    def join(self) -> _Client:
        client = _Client()
        self._clients.add(client)
        return client

    def leave(self, client: _Client) -> None:
        self._clients.discard(client)

    async def _end_when_done(self, done: asyncio.Task[None]) -> None:
        try:
            await done
        except Exception:
            log.exception("the run stopped with an error")
        if self.run is not None:
            self.publish(self.run.model_copy(update={"state": "ended"}))


def create_app(hub: Hub, app_dir: Path = APP_DIR) -> FastAPI:
    app = FastAPI(
        title="C-UAS dashboard", docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.exception_handler(RequestValidationError)
    async def bad_body(request: Request, error: RequestValidationError) -> JSONResponse:
        details = "; ".join(e.get("msg", "invalid") for e in error.errors())
        return JSONResponse(status_code=422, content={"detail": details})

    @app.get("/api/profiles")
    def get_profiles() -> list[SiteProfile]:
        return hub.profiles

    @app.post("/api/runs")
    async def start_run(request: StartRun) -> RunInfo:
        try:
            return await hub.start(request)
        except Busy as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/api/run/control")
    async def control_run(
        request: RunControl,
    ) -> RunInfo:  # in the loop: it moves the clock
        try:
            return hub.control(request)
        except LookupError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/clips/{station_id}/{clip_id}")
    def get_clip(station_id: str, clip_id: str) -> FileResponse:
        path = hub.clip(station_id, clip_id)
        if path is None:
            raise HTTPException(status_code=404, detail="no such recording in this run")
        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/contract")
    def get_contract() -> dict:
        return contract_schema()

    @app.websocket("/ws")
    async def stream(websocket: WebSocket) -> None:
        await websocket.accept()
        client = hub.join()
        sender = asyncio.create_task(_send(websocket, client, hub.hello()))
        try:
            while True:  # clients send nothing; reading notices when they go
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            hub.leave(client)

    app.mount(
        "/reference",
        StaticFiles(directory=REFERENCE_DIR, html=True),
        name="reference",
    )
    if (app_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=app_dir, html=True), name="app")
    else:

        @app.get("/")
        def no_dashboard_yet() -> RedirectResponse:
            return RedirectResponse("/reference/")

    return app


async def _send(websocket: WebSocket, client: _Client, hello: Hello) -> None:
    try:
        await websocket.send_text(hello.model_dump_json())
        while True:
            for text in await client.take():
                await websocket.send_text(text)
    except (WebSocketDisconnect, RuntimeError):
        return  # the client went while a message was on its way


async def serve(app: FastAPI, host: str, port: int) -> None:
    """Serve until stopped, in the caller's event loop."""
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    await uvicorn.Server(config).serve()

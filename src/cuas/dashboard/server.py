"""The dashboard server: the WebSocket stream and HTTP API of docs/dashboard_contract.md.

A ``Hub`` holds the one current run, the latest frame and the connected clients. Runs come from
a ``Launcher`` the composition root supplies (``scripts/run_demo.py``), because the dashboard may
not start the simulator itself. Labels and exports go to the evidence keeper as messages on the
run's evidence bus, and the answer is the record carrying the same request ID: the dashboard
never writes evidence itself. Everything is served locally; the API documentation pages are
turned off because they load their assets from a CDN.

Mount paths: the API under ``/api``, the stream at ``/ws``, the reference page at ``/reference/``,
and the operator dashboard from ``static/app/`` at ``/``. Until that exists, ``/`` redirects to
the reference page.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Protocol

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from cuas.bus import Bus
from cuas.clock import SimClock
from cuas.dashboard.basemap import Basemap
from cuas.dashboard.contract import (
    EvidenceEvent,
    ExportResult,
    Frame,
    Hello,
    Label,
    LabelRequest,
    LabelResult,
    ModelStatus,
    RunControl,
    RunInfo,
    SiteProfile,
    StartRun,
    contract_schema,
)
from cuas.schemas import EvidenceRecord, ExportRequest, Message, OperatorLabel
from cuas.schemas.topics import EVIDENCE_RECORD, EXPORT_REQUEST, OPERATOR_LABEL

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
REFERENCE_DIR = STATIC / "reference"
APP_DIR = STATIC / "app"
CLIP_ID = re.compile(r"^[0-9a-f]{16}$")
# Camera clips and microphone recordings, as the recorder keeps them.
CLIP_TYPES = {".mp4": "video/mp4", ".wav": "audio/wav"}

Outgoing = Hello | RunInfo | Frame | EvidenceEvent | ModelStatus
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
    run_dir: Path | None = None
    evidence: Bus | None = None
    """The evidence bus, for labels and exports. ``None`` when the run keeps no evidence."""


class Launcher(Protocol):
    def profiles(self) -> list[SiteProfile]: ...

    async def start(self, request: StartRun, publish: Publish) -> Started:
        """Start a run. Raises ``LookupError`` for a profile or scenario it does not have."""
        ...


class Busy(Exception):
    """A run is already going."""


class ModelsNotReady(Exception):
    """A recorded-media run was asked for before the models loaded, or after they failed."""


class NoAnswer(Exception):
    """The evidence keeper did not answer a label or export in time."""


class UnknownAlert(Exception):
    """No alert with that ID has been raised in this run."""


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
    def __init__(
        self, launcher: Launcher, request_timeout_s: float | None = None
    ) -> None:
        """``request_timeout_s``: how long a label or export waits for the evidence keeper;
        ``None`` waits until the run ends."""
        self._launcher = launcher
        self._request_timeout_s = request_timeout_s
        self.profiles = launcher.profiles()
        self.run: RunInfo | None = None
        self.frame: Frame | None = None
        self.models: ModelStatus | None = None
        """Set by the first ``models`` message; ``None`` while the server loads no models."""
        self._started: Started | None = None
        self._clients: set[_Client] = set()
        self._watcher: asyncio.Task[None] | None = None
        self._listener: asyncio.Task[None] | None = None
        self._alert_ids: set[str] = set()
        self._pending: dict[str, asyncio.Future[EvidenceRecord]] = {}
        self._request_numbers = count(1)

    @property
    def active(self) -> bool:
        return self.run is not None and self.run.state != "ended"

    def hello(self) -> Hello:
        return Hello(
            profiles=self.profiles, run=self.run, frame=self.frame, models=self.models
        )

    async def start(self, request: StartRun) -> RunInfo:
        if self.active:
            raise Busy("a run is already going")
        if request.recorded_media:
            self._check_models()
        started = await self._launcher.start(request, self.publish)
        self._started, self.frame = started, None
        self._alert_ids, self._pending = set(), {}
        if started.evidence is not None:  # subscribed before the run can write a record
            records = started.evidence.subscribe(EVIDENCE_RECORD)
            self._listener = asyncio.create_task(self._listen(records))
        self.publish(started.run)
        self._watcher = asyncio.create_task(self._end_when_done(started))
        return started.run

    def _check_models(self) -> None:
        models = self.models
        if models is None or models.state == "ready":
            return
        if models.state == "loading":
            raise ModelsNotReady("the AI models are still loading")
        problems = [
            f"{s.name}: {s.detail}"
            for s in models.steps
            if s.state in ("missing", "failed")
        ]
        raise ModelsNotReady(f"recorded media is unavailable: {'; '.join(problems)}")

    async def stop(self) -> RunInfo:
        """End the run at its next tick, the way a finished run ends: the pipeline drains and
        the evidence keeper exports every alert. Returns once it has ended, ready for a new run."""
        started, watcher = self._started, self._watcher
        if not self.active or started is None or watcher is None:
            raise LookupError("no run is going")
        started.clock.stop()
        await asyncio.shield(watcher)
        if self.run is None:
            raise LookupError("no run is going")
        return self.run

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

    async def label(self, alert_id: str, label: Label) -> LabelResult:
        started = self._evidence_run(alert_id)
        request = OperatorLabel(
            alert_id=alert_id,
            label=label,
            t=started.clock.now,
            request_id=self._request_id(),
        )
        record = await self._ask(started, OPERATOR_LABEL, request)
        return LabelResult(
            alert_id=alert_id, seq=record.seq, record_hash=record.record_hash
        )

    async def export(self, alert_id: str) -> ExportResult:
        started = self._evidence_run(alert_id)
        request = ExportRequest(
            alert_id=alert_id, t=started.clock.now, request_id=self._request_id()
        )
        record = await self._ask(started, EXPORT_REQUEST, request)
        package = record.files[0]
        assert started.run_dir is not None
        text = (started.run_dir / package.path).read_text(encoding="utf-8")
        return ExportResult(
            alert_id=alert_id,
            path=package.path,
            sha256=package.sha256,
            package=json.loads(text),
        )

    def _evidence_run(self, alert_id: str) -> Started:
        started = self._started
        if not self.active or started is None or started.evidence is None:
            raise LookupError("no run that keeps evidence is going")
        if alert_id not in self._alert_ids:
            raise UnknownAlert(f"no alert {alert_id!r} in this run")
        return started

    def _request_id(self) -> str:
        return f"req-{next(self._request_numbers)}"

    async def _ask(
        self, started: Started, topic: str, request: OperatorLabel | ExportRequest
    ) -> EvidenceRecord:
        """Publish a request and wait for the record that answers it."""
        assert started.evidence is not None
        waiting = asyncio.get_running_loop().create_future()
        self._pending[request.request_id] = waiting
        try:
            await started.evidence.publish(topic, request)
        except RuntimeError as error:  # the evidence bus closed: the run is ending
            self._pending.pop(request.request_id, None)
            raise LookupError("the run has ended") from error
        try:
            return await asyncio.wait_for(waiting, self._request_timeout_s)
        except TimeoutError as error:
            self._pending.pop(request.request_id, None)
            raise NoAnswer(
                f"the evidence keeper did not answer in {self._request_timeout_s:g} s;"
                " see the server console"
            ) from error

    async def _listen(self, records: AsyncIterator[Message]) -> None:
        async for record in records:
            if not isinstance(record, EvidenceRecord):
                continue
            if record.kind == "alert":
                self._alert_ids.add(record.alert_id)
            waiting = self._pending.pop(record.request_id or "", None)
            if waiting is not None and not waiting.done():
                waiting.set_result(record)
            if self.run is not None:
                self.publish(
                    EvidenceEvent(
                        run_id=self.run.run_id,
                        seq=record.seq,
                        kind=record.kind,
                        alert_id=record.alert_id,
                        t=record.t,
                        record_hash=record.record_hash,
                    )
                )
        for (
            waiting
        ) in self._pending.values():  # requests the run ended before answering
            if not waiting.done():
                waiting.set_exception(LookupError("the run has ended"))
        self._pending.clear()

    def publish(self, message: Outgoing) -> None:
        if isinstance(message, RunInfo):
            self.run = message
        elif isinstance(message, Frame):
            self.frame = message
        elif isinstance(message, ModelStatus):
            self.models = message
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
        folder = self._started.clips_dir / f"station_{station_id}"
        paths = (folder / f"{clip_id}{suffix}" for suffix in CLIP_TYPES)
        return next((path for path in paths if path.is_file()), None)

    def join(self) -> _Client:
        client = _Client()
        self._clients.add(client)
        return client

    def leave(self, client: _Client) -> None:
        self._clients.discard(client)

    async def _end_when_done(self, started: Started) -> None:
        try:
            await started.done
        except Exception:
            log.exception("the run stopped with an error")
            reason = "failed"
        else:
            reason = "stopped" if started.clock.stopped else "completed"
        if self.run is not None:
            update = {"state": "ended", "ended_reason": reason}
            self.publish(self.run.model_copy(update=update))


def create_app(
    hub: Hub, app_dir: Path = APP_DIR, basemap: Basemap | None = None
) -> FastAPI:
    """``basemap`` is drawn under the site; without one, frontends draw the local grid."""
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
        except (Busy, ModelsNotReady) as error:
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

    @app.post("/api/run/stop")
    async def stop_run() -> RunInfo:
        try:
            return await hub.stop()
        except LookupError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/alerts/{alert_id}/label")
    async def label_alert(alert_id: str, request: LabelRequest) -> LabelResult:
        try:
            return await hub.label(alert_id, request.label)
        except UnknownAlert as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except NoAnswer as error:
            raise HTTPException(status_code=504, detail=str(error)) from error
        except LookupError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/alerts/{alert_id}/export")
    async def export_alert(alert_id: str) -> ExportResult:
        try:
            return await hub.export(alert_id)
        except UnknownAlert as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except NoAnswer as error:
            raise HTTPException(status_code=504, detail=str(error)) from error
        except LookupError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/clips/{station_id}/{clip_id}")
    def get_clip(station_id: str, clip_id: str) -> FileResponse:
        path = hub.clip(station_id, clip_id)
        if path is None:
            raise HTTPException(status_code=404, detail="no such recording in this run")
        return FileResponse(path, media_type=CLIP_TYPES[path.suffix])

    @app.get("/api/basemap")
    def get_basemap() -> Basemap:
        if basemap is None:
            raise HTTPException(
                status_code=404,
                detail="no basemap on this machine: draw the local grid",
            )
        return basemap

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

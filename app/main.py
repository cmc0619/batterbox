"""BatterBox FastAPI application entry point."""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, db
from .routers import clips, playback, players, settings, teams
from .services import audio, gpio

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("batterbox")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    audio.ws_manager.loop = asyncio.get_running_loop()
    gpio.init_gpio()
    log.info(
        "BatterBox ready (DATA_DIR=%s, AUDIO_BACKEND=%s, MOCK_GPIO=%s)",
        config.DATA_DIR,
        config.AUDIO_BACKEND,
        config.MOCK_GPIO,
    )
    yield


app = FastAPI(title="BatterBox", lifespan=lifespan)

# Private hotspot app — allow all origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for sub in ("", "clips", "sources", "photos"):
    os.makedirs(os.path.join(config.DATA_DIR, sub), exist_ok=True)

app.include_router(teams.router)
app.include_router(players.router)
app.include_router(clips.router)
app.include_router(playback.router)
app.include_router(settings.router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await audio.ws_manager.connect(websocket)
    state = audio.get_state()
    state.pop("audio_warning", None)  # WS state shape per contract
    await websocket.send_text(json.dumps({"event": "state", **state}))
    try:
        while True:  # clients never send; this just holds the socket open
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        audio.ws_manager.disconnect(websocket)


app.mount("/media", StaticFiles(directory=config.DATA_DIR), name="media")

# Static frontend is owned by another slice; mount only when present.
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")

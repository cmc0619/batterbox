"""Playback endpoints (per docs/API.md). All state transitions go through
services.audio, which also broadcasts over /ws."""

from fastapi import APIRouter, HTTPException

from ..models import PlayClipRequest, PlayRequest, VolumeSet
from ..services import audio

router = APIRouter(prefix="/api/playback", tags=["playback"])


@router.post("/play")
def play(body: PlayRequest):
    state = audio.play(body.player_id, body.type)
    if state is None:
        raise HTTPException(
            404, f"player {body.player_id} has no active {body.type} clip"
        )
    return state


@router.post("/play_clip")
def play_clip(body: PlayClipRequest):
    state = audio.play_clip(body.clip_id)
    if state is None:
        raise HTTPException(404, f"clip {body.clip_id} not found")
    return state


@router.post("/stop")
def stop():
    return audio.stop()


@router.post("/volume")
def set_volume(body: VolumeSet):
    return audio.set_volume(body.volume)


@router.post("/next")
def next_batter():
    state, err = audio.play_next()
    if state is None:
        raise HTTPException(404, err)
    return state


@router.get("/state")
def get_state():
    return audio.get_state()

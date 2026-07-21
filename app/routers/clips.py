"""Clip endpoints: list, async imports (youtube/upload), jobs, render,
activate, delete (per docs/API.md)."""

import os

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from .. import db
from ..models import ClipCreate, YoutubeImport
from ..services import clipper

router = APIRouter(tags=["clips"])

UPLOAD_EXTS = {".mp3", ".m4a"}


@router.get("/api/players/{player_id}/clips")
def list_clips(player_id: int):
    if db.get_player(player_id) is None:
        raise HTTPException(404, f"player {player_id} not found")
    return db.list_clips(player_id)


@router.post("/api/clips/import/youtube", status_code=202)
def import_youtube(body: YoutubeImport):
    if db.get_player(body.player_id) is None:
        raise HTTPException(404, f"player {body.player_id} not found")
    job = clipper.start_youtube_job(body.player_id, body.type, body.url)
    return {"job_id": job["job_id"]}


@router.post("/api/clips/import/upload", status_code=202)
async def import_upload(player_id: int, type: str, file: UploadFile = File(...)):
    if type not in ("walkup", "homerun"):
        raise HTTPException(400, "type must be walkup or homerun")
    if db.get_player(player_id) is None:
        raise HTTPException(404, f"player {player_id} not found")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in UPLOAD_EXTS:
        raise HTTPException(400, "file must be mp3 or m4a")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    job = clipper.start_upload_job(player_id, type, ext, data)
    return {"job_id": job["job_id"]}


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = clipper.get_job(job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id} not found")
    return clipper.job_public(job)


@router.post("/api/clips", status_code=201)
def create_clip(body: ClipCreate):
    if db.get_player(body.player_id) is None:
        raise HTTPException(404, f"player {body.player_id} not found")
    try:
        return clipper.create_clip(
            job_id=body.job_id,
            player_id=body.player_id,
            clip_type=body.type,
            trim_start_sec=body.trim_start_sec,
            trim_end_sec=body.trim_end_sec,
            fade_in_ms=body.fade_in_ms,
            fade_out_ms=body.fade_out_ms,
            volume_boost_db=body.volume_boost_db,
        )
    except clipper.JobError as e:
        raise HTTPException(400, str(e)) from e
    except clipper.RenderError as e:
        raise HTTPException(500, str(e)) from e


@router.post("/api/clips/{clip_id}/activate")
def activate_clip(clip_id: int):
    if db.get_clip(clip_id) is None:
        raise HTTPException(404, f"clip {clip_id} not found")
    db.activate_clip(clip_id)
    return db.get_clip(clip_id)


@router.delete("/api/clips/{clip_id}", status_code=204)
def delete_clip(clip_id: int):
    if not db.delete_clip(clip_id):
        raise HTTPException(404, f"clip {clip_id} not found")
    return Response(status_code=204)

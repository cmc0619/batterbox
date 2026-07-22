"""Hype clip endpoints: crowd stingers not tied to any player (per
docs/API.md). Same import-job/render pipeline as player clips."""

import os

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from .. import db
from ..models import ClipPatch, HypeCreate, HypeYoutubeImport
from ..services import clipper

router = APIRouter(tags=["hype"])


def _validate_title(title: str | None) -> str:
    t = (title or "").strip()
    if not t or len(t) > 80:
        raise HTTPException(400, "title must be 1–80 characters")
    return t


@router.get("/api/hype")
def list_hype():
    return db.list_hype()


@router.post("/api/hype/import/youtube", status_code=202)
def import_youtube(body: HypeYoutubeImport):
    _validate_title(body.title)
    job = clipper.start_hype_youtube_job(body.url)
    return {"job_id": job["job_id"]}


@router.post("/api/hype/import/upload", status_code=202)
async def import_upload(title: str, file: UploadFile = File(...)):
    _validate_title(title)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in clipper.UPLOAD_EXTS:
        raise HTTPException(400, "file must be mp3 or m4a")
    # Bounded read: never pull more than the cap (+1 to detect overflow)
    # into memory, whatever the client sends.
    data = await file.read(clipper.MAX_UPLOAD_BYTES + 1)
    if len(data) > clipper.MAX_UPLOAD_BYTES:
        raise HTTPException(400, "file must be 50MB or smaller")
    if not data:
        raise HTTPException(400, "empty file")
    job = clipper.start_hype_upload_job(ext, data)
    return {"job_id": job["job_id"]}


@router.post("/api/hype", status_code=201)
def create_hype(body: HypeCreate):
    try:
        return clipper.create_hype(
            job_id=body.job_id,
            title=body.title,
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


@router.get("/api/hype/{hype_id}/edit_context")
def edit_context(hype_id: int):
    if db.get_hype(hype_id) is None:
        raise HTTPException(404, f"hype clip {hype_id} not found")
    try:
        return clipper.edit_context_hype(hype_id)
    except clipper.SourceMissingError as e:
        raise HTTPException(409, str(e)) from e
    except clipper.RenderError as e:
        raise HTTPException(500, str(e)) from e


@router.patch("/api/hype/{hype_id}")
def patch_hype(hype_id: int, body: ClipPatch):
    if db.get_hype(hype_id) is None:
        raise HTTPException(404, f"hype clip {hype_id} not found")
    try:
        return clipper.rerender_hype(
            hype_id=hype_id,
            trim_start_sec=body.trim_start_sec,
            trim_end_sec=body.trim_end_sec,
            fade_in_ms=body.fade_in_ms,
            fade_out_ms=body.fade_out_ms,
            volume_boost_db=body.volume_boost_db,
        )
    except clipper.SourceMissingError as e:
        raise HTTPException(409, str(e)) from e
    except clipper.JobError as e:
        raise HTTPException(400, str(e)) from e
    except clipper.RenderError as e:
        raise HTTPException(500, str(e)) from e


@router.delete("/api/hype/{hype_id}", status_code=204)
def delete_hype(hype_id: int):
    if not db.delete_hype(hype_id):
        raise HTTPException(404, f"hype clip {hype_id} not found")
    return Response(status_code=204)

"""Player endpoints: CRUD, reorder, photo upload (per docs/API.md)."""

import os
import uuid

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from .. import config, db
from ..models import PlayerCreate, PlayersReorder, PlayerUpdate

router = APIRouter(tags=["players"])

MAX_PHOTO_BYTES = 5 * 1024 * 1024
PHOTO_EXTS = {".jpg", ".jpeg", ".png"}


@router.get("/api/teams/{team_id}/players")
def list_players(team_id: int):
    if db.get_team(team_id) is None:
        raise HTTPException(404, f"team {team_id} not found")
    return db.list_players(team_id)


@router.post("/api/teams/{team_id}/players", status_code=201)
def create_player(team_id: int, body: PlayerCreate):
    if db.get_team(team_id) is None:
        raise HTTPException(404, f"team {team_id} not found")
    return db.create_player(team_id, body.name, body.jersey_number)


@router.patch("/api/players/{player_id}")
def update_player(player_id: int, body: PlayerUpdate):
    if db.get_player(player_id) is None:
        raise HTTPException(404, f"player {player_id} not found")
    return db.update_player(player_id, body.model_dump(exclude_unset=True))


@router.delete("/api/players/{player_id}", status_code=204)
def delete_player(player_id: int):
    if not db.delete_player(player_id):
        raise HTTPException(404, f"player {player_id} not found")
    return Response(status_code=204)


@router.post("/api/teams/{team_id}/players/reorder", status_code=204)
def reorder_players(team_id: int, body: PlayersReorder):
    if db.get_team(team_id) is None:
        raise HTTPException(404, f"team {team_id} not found")
    roster_ids = {p["id"] for p in db.list_players(team_id)}
    if len(body.player_ids) != len(set(body.player_ids)) or set(
        body.player_ids
    ) != roster_ids:
        # A partial or foreign list would silently leave stale sort_order
        # on the players it omits.
        raise HTTPException(
            400, "player_ids must contain every player of the team exactly once"
        )
    db.reorder_players(team_id, body.player_ids)
    return Response(status_code=204)


@router.post("/api/players/{player_id}/photo")
async def upload_photo(player_id: int, file: UploadFile = File(...)):
    player = db.get_player(player_id)
    if player is None:
        raise HTTPException(404, f"player {player_id} not found")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in PHOTO_EXTS:
        raise HTTPException(400, "photo must be jpg or png")
    # Bounded read (cap + 1 detects overflow) — an unbounded read() would
    # copy an arbitrarily large request body into memory before the check.
    data = await file.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(400, "photo must be 5MB or smaller")
    if not (
        data.startswith(b"\xff\xd8\xff")  # JPEG
        or data.startswith(b"\x89PNG\r\n\x1a\n")  # PNG
    ):
        raise HTTPException(400, "file content is not a jpg or png image")
    filename = f"player_{player_id}{ext}"
    photos_dir = os.path.join(config.DATA_DIR, "photos")
    # Temp-then-replace: a failed write can't leave the player pointing at a
    # truncated (or already-deleted) photo.
    tmp = os.path.join(photos_dir, f"{filename}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, os.path.join(photos_dir, filename))
    except OSError as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise HTTPException(500, f"failed to store photo: {e}") from e
    photo_url = f"/media/photos/{filename}"
    db.set_player_photo(player_id, photo_url)
    # Only now remove a previous photo with a different extension (same-ext
    # uploads were replaced in place by the rename above).
    old = player.get("photo_url")
    if old and os.path.basename(old) != filename:
        old_path = os.path.join(config.DATA_DIR, "photos", os.path.basename(old))
        if os.path.exists(old_path):
            os.remove(old_path)
    return {"photo_url": photo_url}

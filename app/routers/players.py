"""Player endpoints: CRUD, reorder, photo upload (per docs/API.md)."""

import os

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
    data = await file.read()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(400, "photo must be 5MB or smaller")
    old = player.get("photo_url")
    if old:
        old_path = os.path.join(config.DATA_DIR, "photos", os.path.basename(old))
        if os.path.exists(old_path):
            os.remove(old_path)
    filename = f"player_{player_id}{ext}"
    with open(os.path.join(config.DATA_DIR, "photos", filename), "wb") as f:
        f.write(data)
    photo_url = f"/media/photos/{filename}"
    db.set_player_photo(player_id, photo_url)
    return {"photo_url": photo_url}

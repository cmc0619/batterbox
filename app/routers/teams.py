"""Teams + active-team endpoints (per docs/API.md)."""

from fastapi import APIRouter, HTTPException, Response

from .. import db
from ..models import ActiveTeamSet, TeamCreate, TeamUpdate

router = APIRouter(prefix="/api/teams", tags=["teams"])


# NOTE: /active routes must be registered before /{team_id} routes.
@router.get("/active")
def get_active_team():
    return {"team_id": db.get_active_team_id()}


@router.post("/active")
def set_active_team(body: ActiveTeamSet):
    if db.get_team(body.team_id) is None:
        raise HTTPException(404, f"team {body.team_id} not found")
    db.set_active_team_id(body.team_id)
    return {"team_id": body.team_id}


@router.get("")
def list_teams():
    return db.list_teams()


@router.post("", status_code=201)
def create_team(body: TeamCreate):
    return db.create_team(body.name)


@router.patch("/{team_id}")
def update_team(team_id: int, body: TeamUpdate):
    team = db.update_team(team_id, body.name)
    if team is None:
        raise HTTPException(404, f"team {team_id} not found")
    return team


@router.delete("/{team_id}", status_code=204)
def delete_team(team_id: int):
    if not db.delete_team(team_id):
        raise HTTPException(404, f"team {team_id} not found")
    return Response(status_code=204)

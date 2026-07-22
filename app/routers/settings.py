"""Settings endpoints (per docs/API.md)."""

from fastapi import APIRouter

from .. import db
from ..models import SettingsPatch
from ..services import audio

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings():
    return db.public_settings()


@router.patch("")
def patch_settings(body: SettingsPatch):
    patch = body.model_dump(exclude_unset=True)
    for key, value in patch.items():
        if value is None:
            # An explicit null would be persisted as the string "None" and
            # poison every later int()/float() read of that setting.
            continue
        if key == "master_volume":
            continue  # handled via audio.set_volume below (persists + broadcasts)
        if isinstance(value, bool):
            value = "true" if value else "false"
        db.set_setting(key, value)
    if patch.get("master_volume") is not None:
        audio.set_volume(patch["master_volume"])
    return db.public_settings()

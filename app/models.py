"""Pydantic request models."""

from typing import Literal

from pydantic import BaseModel, Field

ClipType = Literal["walkup", "homerun"]


class TeamCreate(BaseModel):
    name: str


class TeamUpdate(BaseModel):
    name: str


class ActiveTeamSet(BaseModel):
    team_id: int


class PlayerCreate(BaseModel):
    name: str
    jersey_number: int | None = None


class PlayerUpdate(BaseModel):
    name: str | None = None
    jersey_number: int | None = None
    absent: bool | None = None


class PlayersReorder(BaseModel):
    player_ids: list[int]


class YoutubeImport(BaseModel):
    player_id: int
    type: ClipType
    url: str


class ClipCreate(BaseModel):
    job_id: str
    player_id: int
    type: ClipType
    trim_start_sec: float
    trim_end_sec: float
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    volume_boost_db: float = 0.0


class ClipPatch(BaseModel):
    trim_start_sec: float
    trim_end_sec: float
    fade_in_ms: int
    fade_out_ms: int
    volume_boost_db: float


class PlayRequest(BaseModel):
    player_id: int
    type: ClipType


class PlayClipRequest(BaseModel):
    clip_id: int


class VolumeSet(BaseModel):
    volume: int = Field(ge=0, le=100)


class BluetoothPairingStart(BaseModel):
    duration_sec: int = Field(default=120, ge=5, le=3600)


class BluetoothConnectRequest(BaseModel):
    mac: str = Field(pattern=r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


class WifiCredentials(BaseModel):
    # Kept loose on purpose: WPA2 rules (ssid 1-32, password 8-63 printable
    # ASCII) are enforced by services.wifi so failures come back as 400 with
    # a human-readable detail instead of a pydantic 422.
    ssid: str
    password: str


class SettingsPatch(BaseModel):
    default_snippet_length: int | None = None
    master_volume: int | None = Field(default=None, ge=0, le=100)
    audio_output: str | None = None
    mock_gpio: bool | None = None

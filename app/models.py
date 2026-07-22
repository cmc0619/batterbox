"""Pydantic request models."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

ClipType = Literal["walkup", "homerun", "walkout"]


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


# NaN/Infinity pass arithmetic comparisons silently (NaN <= x is always
# False), so a non-finite trim/boost would sail through service validation,
# get persisted, and then break JSON serialization of every response that
# includes the row. Reject at the model boundary. Boost is bounded to a
# sane window around the editor UI's -12..+12 range.
FiniteSec = Annotated[float, Field(allow_inf_nan=False)]
BoostDb = Annotated[float, Field(ge=-24, le=24, allow_inf_nan=False)]


class ClipCreate(BaseModel):
    job_id: str
    player_id: int
    type: ClipType
    trim_start_sec: FiniteSec
    trim_end_sec: FiniteSec
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    volume_boost_db: BoostDb = 0.0


class ClipPatch(BaseModel):
    trim_start_sec: FiniteSec
    trim_end_sec: FiniteSec
    fade_in_ms: int
    fade_out_ms: int
    volume_boost_db: BoostDb


class PlayRequest(BaseModel):
    player_id: int
    type: ClipType


class PlayClipRequest(BaseModel):
    clip_id: int


class PlayHypeRequest(BaseModel):
    hype_id: int


class StopRequest(BaseModel):
    # Browser `ended` handlers echo the play_id they were playing; the stop
    # is ignored if another play superseded it. Manual stops send no body.
    play_id: int | None = None


class HypeYoutubeImport(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    url: str


class HypeCreate(BaseModel):
    job_id: str
    title: str = Field(min_length=1, max_length=80)
    trim_start_sec: FiniteSec
    trim_end_sec: FiniteSec
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    volume_boost_db: BoostDb = 0.0


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
    default_snippet_length: int | None = Field(default=None, ge=3, le=300)
    master_volume: int | None = Field(default=None, ge=0, le=100)
    audio_output: str | None = None
    mock_gpio: bool | None = None

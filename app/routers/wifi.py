"""Wi-Fi hotspot endpoints (per docs/API.md). All work goes through
services.wifi, which degrades to available=false when nmcli/NetworkManager
is absent — validation and availability failures produce 400 with detail;
a failed radio change rides back in status.detail where noted in the contract."""

from fastapi import APIRouter, HTTPException

from ..models import WifiCredentials
from ..services import wifi

router = APIRouter(prefix="/api/wifi", tags=["wifi"])


@router.get("/status")
def status():
    return wifi.get_status()


@router.post("/hotspot")
def start_hotspot(body: WifiCredentials):
    status, err = wifi.enable_hotspot(body.ssid, body.password)
    if err:
        raise HTTPException(400, err)
    return status


@router.post("/hotspot/off")
def stop_hotspot():
    status, err = wifi.disable_hotspot()
    if err and not status.get("available"):
        raise HTTPException(400, err)
    # A failed "connection down" on an available adapter rides back in detail.
    return status


@router.post("/settings")
def save_settings(body: WifiCredentials):
    status, err = wifi.save_settings(body.ssid, body.password)
    if err:
        raise HTTPException(400, err)
    return status

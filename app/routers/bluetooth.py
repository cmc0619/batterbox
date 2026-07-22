"""Bluetooth speaker pairing endpoints (per docs/API.md). All work goes
through services.bluetooth, which degrades to available=false when BlueZ
is absent. HTTP errors (400) come from "unavailable" and from a pairing
start that couldn't make the adapter discoverable/pairable; a failed
connect to an available adapter rides back in status.detail (200)."""

from fastapi import APIRouter, HTTPException

from ..models import BluetoothConnectRequest, BluetoothPairingStart
from ..services import bluetooth

router = APIRouter(prefix="/api/bluetooth", tags=["bluetooth"])


@router.get("/status")
def status():
    return bluetooth.get_status()


@router.post("/pairing")
def start_pairing(body: BluetoothPairingStart):
    status, err = bluetooth.enter_pairing(body.duration_sec)
    if err:
        raise HTTPException(400, err)
    return status


@router.post("/pairing/stop")
def stop_pairing():
    return bluetooth.exit_pairing()


@router.post("/connect")
def connect_device(body: BluetoothConnectRequest):
    status, err = bluetooth.connect(body.mac)
    if err and not status.get("available"):
        raise HTTPException(400, err)
    # Connect failure of an available adapter rides back in status.detail.
    return status

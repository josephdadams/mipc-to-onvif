"""
mipc-to-onvif — MIPC cloud camera → ONVIF translation layer.

For each camera on the MIPC account:
  1. Fetches its RTSP URL from the MIPC cloud
  2. Registers it as a path in mediamtx (local RTSP relay)
  3. Starts a minimal ONVIF HTTP server on a dedicated port

Camera N is accessible at:
  ONVIF:  http://<host_ip>:<onvif_base_port + N>/onvif/device_service
  RTSP:   rtsp://<host_ip>:<rtsp_port>/<camera_serial>
  UI:     http://<host_ip>:<web_port>
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone

from urllib.parse import urlparse

from config import load as load_config
from mipc.account import MIPCAccount, MIPCError
from onvif.server import ONVIFCameraServer
from rtsp.ffmpeg import FFmpegManager
from rtsp.manager import MediaMTXManager
from state import CameraState, ProxyState
from web.server import WebUIServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("main")

REFRESH_INTERVAL = 300  # seconds between RTSP token refreshes
CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config.yml")


# ---------------------------------------------------------------------------
# Camera initialisation (called on startup and on config save via web UI)
# ---------------------------------------------------------------------------

async def init_cameras(
    cfg: dict,
    mtx: MediaMTXManager,
    ffmpeg: FFmpegManager,
    state: ProxyState,
    existing_servers: list[ONVIFCameraServer],
) -> list[ONVIFCameraServer]:
    """
    Tear down any existing ONVIF servers, re-authenticate with MIPC,
    and bring up fresh servers for all cameras in the account.
    Returns the new server list.
    """
    for s in existing_servers:
        await s.stop()
    await ffmpeg.stop_all()

    proxy_cfg = cfg.get("proxy", {})
    host_ip: str = proxy_cfg.get("host_ip", "127.0.0.1")
    onvif_base_port: int = proxy_cfg.get("onvif_base_port", 8081)
    rtsp_port: int = proxy_cfg.get("rtsp_port", 8554)

    mipc_cfg = cfg.get("mipc", {})
    username = mipc_cfg.get("username", "")
    password = mipc_cfg.get("password", "")

    if not username or not password:
        state.connected = False
        state.error = "MIPC credentials not configured — use the web UI."
        state.cameras = []
        log.warning("MIPC credentials missing — waiting for web UI configuration.")
        return []

    account = MIPCAccount(username=username, password=password)

    try:
        log.info("Authenticating with MIPC...")
        await account.authenticate()
        log.info("Fetching device list...")
        devices = await account.get_devices()
    except MIPCError as err:
        state.connected = False
        state.error = str(err)
        state.cameras = []
        log.error("MIPC init failed: %s", err)
        return []

    state.connected = True
    state.error = None
    state.cameras = []

    if devices:
        log.debug("Raw MIPC device fields: %s", list(devices[0].keys()))

    servers: list[ONVIFCameraServer] = []
    for idx, device in enumerate(devices):
        sn: str = device["sn"]
        name: str = device.get("name") or device.get("dname") or device.get("dev_name") or sn
        online: bool = device.get("stat") == "Online"
        port = onvif_base_port + idx

        log.info("Camera %s (%s, online=%s) → ONVIF port %d", sn, name, online, port)

        if online:
            try:
                rtsp_url = await account.get_stream_url(sn)
                await ffmpeg.start_or_restart(sn, rtsp_url)
            except MIPCError as err:
                log.warning("Stream URL for %s failed: %s", sn, err)

        server = ONVIFCameraServer(
            camera_sn=sn,
            host_ip=host_ip,
            onvif_port=port,
            rtsp_port=rtsp_port,
            rtsp_path=sn,
            snapshot_fetcher=account.get_snapshot,
        )
        await server.start()
        servers.append(server)
        state.cameras.append(CameraState(sn=sn, name=name, online=online, onvif_port=port, rtsp_path=sn))

    state.last_refresh = datetime.now(timezone.utc)

    if devices:
        _print_summary(devices, host_ip, onvif_base_port, rtsp_port)

    # Store account on the state so the refresh loop can use it
    state._account = account  # type: ignore[attr-defined]

    return servers


async def _refresh_loop(state: ProxyState, ffmpeg: FFmpegManager, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        account: MIPCAccount | None = getattr(state, "_account", None)
        if account is None or not state.cameras:
            continue
        log.debug("Refreshing RTSP tokens...")
        for cam in state.cameras:
            if not cam.online:
                continue
            try:
                url = await account.get_stream_url(cam.sn)
                await ffmpeg.start_or_restart(cam.sn, url)
            except MIPCError as err:
                log.warning("Token refresh for %s failed: %s", cam.sn, err)
        state.last_refresh = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run() -> None:
    cfg = load_config(CONFIG_PATH)
    proxy_cfg = cfg.get("proxy", {})
    mediamtx_api: str = proxy_cfg.get("mediamtx_api", "http://mediamtx:9997")
    rtsp_port: int = proxy_cfg.get("rtsp_port", 8554)
    web_port: int = proxy_cfg.get("web_port", 8080)

    mtx = MediaMTXManager(api_url=mediamtx_api)
    mediamtx_host = urlparse(mediamtx_api).hostname or "mediamtx"
    ffmpeg = FFmpegManager(mediamtx_host=mediamtx_host, rtsp_port=rtsp_port)
    state = ProxyState()

    # Web UI starts immediately so users can configure credentials before MIPC is up
    web_ui = WebUIServer(port=web_port, config_path=CONFIG_PATH, state=state)
    await web_ui.start()

    log.info("Waiting for mediamtx to be ready...")
    await mtx.wait_ready()

    # Mutable container so the reinit callback can swap the server list
    servers: list[list[ONVIFCameraServer]] = [[]]

    async def reinit() -> None:
        log.info("Reinitialising cameras (triggered by web UI)...")
        fresh_cfg = load_config(CONFIG_PATH)
        servers[0] = await init_cameras(fresh_cfg, mtx, ffmpeg, state, servers[0])

    state.reinit_callback = reinit

    # Initial camera setup
    servers[0] = await init_cameras(cfg, mtx, ffmpeg, state, [])

    refresh_task = asyncio.create_task(_refresh_loop(state, ffmpeg, REFRESH_INTERVAL))

    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set_result, None)

    log.info("Web UI: http://0.0.0.0:%d", web_port)
    await stop

    log.info("Shutting down...")
    refresh_task.cancel()
    await ffmpeg.stop_all()
    for s in servers[0]:
        await s.stop()
    await web_ui.stop()
    await mtx.close()


def _print_summary(devices: list[dict], host_ip: str, base_port: int, rtsp_port: int) -> None:
    log.info("=" * 60)
    log.info("Cameras ready. Add to NVR using ONVIF protocol:")
    for idx, d in enumerate(devices):
        log.info("  %s  →  %s:%d  (RTSP: rtsp://%s:%d/%s)",
                 d["sn"], host_ip, base_port + idx, host_ip, rtsp_port, d["sn"])
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(run())

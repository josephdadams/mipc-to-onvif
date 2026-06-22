"""
Per-camera ONVIF HTTP server (aiohttp).
Each camera gets its own port. The NVR adds cameras manually by IP:port.
"""

import logging
from typing import Callable, Awaitable

from aiohttp import web

from . import soap

log = logging.getLogger(__name__)

# Type alias: async function that takes a device serial number and returns snapshot bytes
SnapshotFetcher = Callable[[str], Awaitable[bytes]]


def _xml_response(text: str, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        body=text.encode(),
        content_type="application/soap+xml",
    )


class ONVIFCameraServer:
    """ONVIF Device + Media services for a single camera."""

    def __init__(
        self,
        *,
        camera_sn: str,
        host_ip: str,
        onvif_port: int,
        rtsp_port: int,
        rtsp_path: str,
        snapshot_fetcher: SnapshotFetcher,
    ) -> None:
        self._sn = camera_sn
        self._host_ip = host_ip
        self._onvif_port = onvif_port
        self._rtsp_url = f"rtsp://{host_ip}:{rtsp_port}/{rtsp_path}"
        self._snapshot_url = f"http://{host_ip}:{onvif_port}/snapshot"
        self._snapshot_fetcher = snapshot_fetcher
        self._runner: web.AppRunner | None = None

    # ------------------------------------------------------------------
    # Request handlers
    # ------------------------------------------------------------------

    async def _handle_device(self, request: web.Request) -> web.Response:
        body = await request.read()
        action = soap.parse_action(body)
        log.debug("Device action: %s", action)

        if action == "GetSystemDateAndTime":
            return _xml_response(soap.get_system_date_and_time())
        elif action == "GetDeviceInformation":
            return _xml_response(soap.get_device_information(self._sn))
        elif action == "GetCapabilities":
            return _xml_response(soap.get_capabilities(self._host_ip, self._onvif_port))
        elif action == "GetHostname":
            return _xml_response(soap.get_hostname(f"mipc-{self._sn}"))
        elif action == "GetServices":
            return _xml_response(soap.get_services(self._host_ip, self._onvif_port))
        elif action == "GetScopes":
            return _xml_response(soap.get_scopes())
        else:
            log.debug("Unhandled device action: %s", action)
            return _xml_response(soap._envelope(f"<tds:{action}Response/>"))

    async def _handle_media(self, request: web.Request) -> web.Response:
        body = await request.read()
        action = soap.parse_action(body)
        log.debug("Media action: %s", action)

        if action == "GetProfiles":
            return _xml_response(soap.get_profiles(self._sn))
        elif action == "GetVideoSources":
            return _xml_response(soap.get_video_sources())
        elif action == "GetStreamUri":
            return _xml_response(soap.get_stream_uri(self._rtsp_url))
        elif action == "GetSnapshotUri":
            return _xml_response(soap.get_snapshot_uri(self._snapshot_url))
        elif action == "GetVideoEncoderConfigurations":
            return _xml_response(soap.get_video_encoder_configurations())
        else:
            log.debug("Unhandled media action: %s", action)
            return _xml_response(soap._envelope(f"<trt:{action}Response/>"))

    async def _handle_snapshot(self, request: web.Request) -> web.Response:
        try:
            data = await self._snapshot_fetcher(self._sn)
            return web.Response(body=data, content_type="image/jpeg")
        except Exception as err:
            log.warning("Snapshot fetch failed for %s: %s", self._sn, err)
            return web.Response(status=503, text="Snapshot unavailable")

    async def _handle_wsdl(self, request: web.Request) -> web.Response:
        # Some NVRs probe for the WSDL; returning 200 avoids errors
        return web.Response(text="<definitions/>", content_type="text/xml")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post("/onvif/device_service", self._handle_device)
        app.router.add_post("/onvif/device", self._handle_device)
        app.router.add_post("/onvif/media_service", self._handle_media)
        app.router.add_post("/onvif/media", self._handle_media)
        app.router.add_get("/snapshot", self._handle_snapshot)
        app.router.add_get("/onvif/device_service", self._handle_wsdl)
        app.router.add_get("/onvif/media_service", self._handle_wsdl)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._onvif_port)
        await site.start()
        log.info(
            "ONVIF server for %s listening on port %d (RTSP: %s)",
            self._sn, self._onvif_port, self._rtsp_url,
        )

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

"""
FFmpeg-based RTSP relay.

Pulls from a MIPC cloud RTSP URL (which has non-standard SDP that mediamtx
cannot parse natively) and re-publishes a clean stream to mediamtx.
"""

import asyncio
import logging

log = logging.getLogger(__name__)


class FFmpegManager:
    def __init__(self, mediamtx_host: str, rtsp_port: int) -> None:
        self._host = mediamtx_host
        self._port = rtsp_port
        self._procs: dict[str, asyncio.subprocess.Process] = {}

    def _publish_url(self, serial: str) -> str:
        return f"rtsp://{self._host}:{self._port}/{serial}"

    async def start_or_restart(self, serial: str, source_url: str) -> None:
        """Start (or restart) an FFmpeg process that relays source_url → mediamtx."""
        await self.stop(serial)
        cmd = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "warning",
            "-rtsp_transport", "tcp",
            "-i", source_url,
            "-c", "copy",
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            self._publish_url(serial),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._procs[serial] = proc
        log.info("FFmpeg relay started for %s (pid=%d) → %s", serial, proc.pid, self._publish_url(serial))

    async def stop(self, serial: str) -> None:
        proc = self._procs.pop(serial, None)
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()

    async def stop_all(self) -> None:
        for serial in list(self._procs):
            await self.stop(serial)

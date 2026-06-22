"""
mediamtx API manager.
Adds/updates RTSP proxy paths via the mediamtx HTTP API.
"""

import asyncio
import logging

import aiohttp

log = logging.getLogger(__name__)


class MediaMTXManager:
    def __init__(self, api_url: str = "http://localhost:9997") -> None:
        self._api_url = api_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def wait_ready(self, timeout: float = 60.0) -> None:
        """Block until mediamtx API is reachable."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self._api_url}/v3/paths/list",
                        timeout=aiohttp.ClientTimeout(total=2),
                    ) as resp:
                        if resp.status < 500:
                            log.info("mediamtx API is ready")
                            return
            except Exception:
                pass
            await asyncio.sleep(2)
        raise RuntimeError(f"mediamtx API not reachable at {self._api_url} after {timeout}s")

    async def add_or_update_path(self, name: str, source_url: str) -> None:
        """Create or update a mediamtx path to proxy the given RTSP source."""
        session = await self._session_get()
        payload = {
            "source": source_url,
            "sourceOnDemand": False,
        }

        # Try PATCH first (update existing path)
        patch_url = f"{self._api_url}/v3/config/paths/patch/{name}"
        try:
            async with session.patch(patch_url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status in (200, 204):
                    log.debug("Updated mediamtx path: %s → %s", name, source_url)
                    return
        except Exception:
            pass

        # Fall back to add (create new path)
        add_url = f"{self._api_url}/v3/config/paths/add/{name}"
        async with session.post(add_url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status in (200, 201, 204):
                log.info("Added mediamtx path: %s → %s", name, source_url)
            else:
                text = await resp.text()
                log.warning("mediamtx add path %s failed (%d): %s", name, resp.status, text)

    async def remove_path(self, name: str) -> None:
        session = await self._session_get()
        url = f"{self._api_url}/v3/config/paths/delete/{name}"
        try:
            async with session.delete(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                log.debug("Removed mediamtx path %s (status %d)", name, resp.status)
        except Exception as err:
            log.warning("Failed to remove mediamtx path %s: %s", name, err)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

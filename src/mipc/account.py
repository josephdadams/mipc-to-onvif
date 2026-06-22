"""
MIPC cloud API client — adapted from battler2006/homeassistant-mipc-camera.
Home Assistant dependencies removed; uses plain asyncio + requests.
"""

import asyncio
import logging
import math
import ssl
from hashlib import md5 as hashlib_md5
from json import JSONDecodeError, loads as json_loads
from re import IGNORECASE, MULTILINE, sub
from secrets import randbits
from time import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

from .const import (
    BASE_HOST,
    CAM_TIMEOUT,
    MAX_REQUEST_TRY,
    PATHS,
    PRIME,
    ROOT_NUM,
    TIMEOUT,
)
from .crypto import encrypt

log = logging.getLogger(__name__)

MIPC_BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"
BOOTSTRAP_HOSTS = (
    BASE_HOST,
    "http://www.mipcm.com:7080",
    "http://www.mipcm.com",
    "https://oveu17.mipcm.com:7443",
    "http://oveu17.mipcm.com:7080",
)


class MIPCError(Exception):
    pass


# ---------------------------------------------------------------------------
# Pure helpers (identical logic to the HA version)
# ---------------------------------------------------------------------------

def _js_to_int32(value) -> int:
    number = float(value)
    if math.isnan(number) or math.isinf(number) or number == 0:
        return 0
    number = math.copysign(math.floor(abs(number)), number)
    i32 = int(number) % (2 ** 32)
    return i32 - 2 ** 32 if i32 >= 2 ** 31 else i32


def _encode_js_number_bytes(value) -> bytes:
    i32 = _js_to_int32(value)
    number = float(value)
    out = bytearray()
    for shift in (24, 16, 8, 0):
        if number >= (1 << shift):
            out.append((i32 >> shift) & 0xFF)
    return bytes(out)


def _decode_to_bytes(value) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, int):
        return _encode_js_number_bytes(value)
    text = str(value)
    if text.startswith("0x"):
        hex_part = text[2:]
        if len(hex_part) % 2:
            hex_part = f"0{hex_part}"
        return bytes.fromhex(hex_part)
    if text == "":
        return b""
    if text.isdigit():
        return _encode_js_number_bytes(text)
    return text.encode("latin-1", errors="ignore")


def _encode_base64_custom(data: bytes) -> str:
    out = []
    for idx in range(0, len(data), 3):
        chunk = data[idx:idx + 3]
        b1, b2, b3 = chunk[0], (chunk[1] if len(chunk) > 1 else 0), (chunk[2] if len(chunk) > 2 else 0)
        out.append(MIPC_BASE64_ALPHABET[b1 >> 2])
        out.append(MIPC_BASE64_ALPHABET[((b1 & 0x03) << 4) | (b2 >> 4)])
        if len(chunk) > 1:
            out.append(MIPC_BASE64_ALPHABET[((b2 & 0x0F) << 2) | (b3 >> 6)])
        if len(chunk) > 2:
            out.append(MIPC_BASE64_ALPHABET[b3 & 0x3F])
    return "".join(out)


def _build_nid(seq: int, id_: str, shared_key: str, num: int) -> str:
    seq_bytes = _decode_to_bytes(seq)
    id_bytes = _decode_to_bytes(id_) if id_ else b""
    num_bytes = _decode_to_bytes(num) if id_ else b""

    payload = b""
    if seq_bytes:
        payload += bytes([64 + len(seq_bytes)]) + seq_bytes
    if id_bytes:
        payload += bytes([96 + len(id_bytes)]) + id_bytes
    if num_bytes:
        payload += bytes([128 + len(num_bytes)]) + num_bytes

    digest_input = payload
    if shared_key:
        key_bytes = shared_key.encode("latin-1", errors="ignore")
        digest_input += bytes([len(key_bytes)]) + key_bytes

    digest_hex = hashlib_md5(digest_input).hexdigest()
    digest_bytes = _decode_to_bytes(f"0x{digest_hex}")

    token = bytes([32 + len(digest_bytes)]) + digest_bytes + payload
    return _encode_base64_custom(token)


def _gen_private_key() -> str:
    return str(randbits(64) or 1)


def _gen_public_key(private_key: str) -> str:
    return str(pow(int(ROOT_NUM), int(private_key), int(PRIME)))


def _gen_shared_secret(private_key: str, remote_public_key: str) -> str:
    return str(pow(int(remote_public_key), int(private_key), int(PRIME)))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

class _LegacyTLSAdapter(HTTPAdapter):
    def __init__(self, verify: bool, *args, **kwargs):
        self._verify = verify
        super().__init__(*args, **kwargs)

    def _build_ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        if not self._verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        except ssl.SSLError:
            pass
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        except (AttributeError, ValueError):
            pass
        return ctx

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self._build_ssl_context()
        self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize, block=block, **pool_kwargs)


def _sync_get(url: str, verify: bool = False) -> Response:
    session = Session()
    session.mount("https://", _LegacyTLSAdapter(verify=verify))
    response = session.get(url, timeout=TIMEOUT, verify=verify)
    response.raise_for_status()
    response._mipc_session = session
    return response


def _close_response(response: Response) -> None:
    response.close()
    session = getattr(response, "_mipc_session", None)
    if session:
        session.close()


# ---------------------------------------------------------------------------
# MIPCAccount
# ---------------------------------------------------------------------------

class MIPCAccount:
    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._last_authentication: float | None = None
        self._host: str | None = None
        self._qid: str | None = None
        self._seq: int = 0
        self._private = _gen_private_key()
        self._public = _gen_public_key(self._private)
        self._shared_key: str | None = None
        self._key: str | None = None
        self._lid: str | None = None
        self._encrypted_password: str | None = None
        self._sid: str | None = None
        self._nid: str | None = None
        self._device_tokens: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_response(self, response: str) -> dict:
        if not response.startswith("message("):
            raise MIPCError("Unexpected response format from MIPC API")
        try:
            json_str = sub(
                r"(?P<b>[\{\[,])(?P<sb>\s?)(?P<k>[a-z0-9_\.]+)(?P<a>:)(?P<sa>\s?)",
                '\\g<b>"\\g<k>"\\g<a>',
                response[8:-2],
                0,
                IGNORECASE | MULTILINE,
            )
            return json_loads(json_str)
        except (TypeError, ValueError, JSONDecodeError) as err:
            raise MIPCError("Failed to parse MIPC API response") from err

    def _url(self, path_name: str, params: dict | None = None, host: str | None = None) -> str:
        if not host:
            host = self._host or BASE_HOST
        self._seq += 1
        parts = [f"hfrom_handle={self._seq}"]
        for k, v in (params or {}).items():
            parts.append(f"{k}={v}")
        return f"{host}{PATHS[path_name]}?{'&'.join(parts)}"

    async def _get(self, path_name: str, params: dict | None = None, https: bool = False, host: str | None = None) -> dict:
        url = self._url(path_name, params, host=host)
        loop = asyncio.get_running_loop()
        try:
            async with asyncio.timeout(TIMEOUT + 2):
                response: Response = await loop.run_in_executor(None, _sync_get, url, https)
                try:
                    text = response.text
                finally:
                    _close_response(response)
                data = self._parse_response(text)
                self._check_api_error(url, data)
                return data
        except TimeoutError:
            raise MIPCError(f"Timeout getting '{url}'")
        except requests.HTTPError as err:
            raise MIPCError(f"HTTP error getting '{url}': {err}") from err
        except requests.RequestException as err:
            raise MIPCError(f"Request failed for '{url}': {err}") from err

    @staticmethod
    def _check_api_error(url: str, data: dict) -> None:
        d = data.get("data", {})
        for path in (["result"], ["ret", "reason"], ["Result", "Reason"]):
            obj = d
            for key in path:
                obj = obj.get(key) if isinstance(obj, dict) else None
            if isinstance(obj, str) and obj:
                raise MIPCError(f"API error from {url}: {obj}")

    async def _retry(self, method_name: str, **kwargs) -> Any:
        for attempt in range(1, MAX_REQUEST_TRY + 1):
            try:
                return await getattr(self, method_name)(_in_retry=True, **kwargs)
            except MIPCError as err:
                log.warning("attempt %d/%d for %s failed: %s", attempt, MAX_REQUEST_TRY, method_name, err)
                await self._clear()
        raise MIPCError(f"All {MAX_REQUEST_TRY} attempts failed for {method_name}")

    @staticmethod
    def _extract_token(uri: str) -> str | None:
        try:
            params = parse_qs(urlparse(uri).query)
        except Exception:
            return None
        for key in ("dtoken", "token", "auth"):
            vals = params.get(key)
            if vals and vals[0]:
                return vals[0]
        return None

    # ------------------------------------------------------------------
    # Auth flow
    # ------------------------------------------------------------------

    async def _check_session_timeout(self) -> None:
        if not self._last_authentication:
            self._last_authentication = time()
        if time() - self._last_authentication >= CAM_TIMEOUT / 1000:
            await self._clear()
            self._last_authentication = time()

    async def _clear(self) -> None:
        log.debug("Clearing MIPC session")
        self._qid = self._shared_key = self._key = self._lid = None
        self._encrypted_password = self._sid = self._nid = None
        self._private = _gen_private_key()
        self._public = _gen_public_key(self._private)

    async def _get_host(self) -> str:
        last_err = None
        for bootstrap in BOOTSTRAP_HOSTS:
            try:
                resp = await self._get("HOSTS", https=False, host=bootstrap)
                signal_hosts = resp.get("data", {}).get("server", {}).get("signal", [])
                preferred = next(
                    (h for h in signal_hosts if isinstance(h, str) and h.startswith("http://") and "/ccm" in h),
                    None,
                ) or next(
                    (h for h in signal_hosts if isinstance(h, str) and "/ccm" in h),
                    None,
                )
                if not preferred:
                    raise MIPCError("No usable signal host in response")
                self._host = preferred
                log.info("Using MIPC signal host: %s", self._host)
                return self._host
            except MIPCError as err:
                log.debug("Bootstrap %s failed: %s", bootstrap, err)
                last_err = err
        raise last_err or MIPCError("Could not find MIPC host")

    async def _get_qid(self) -> str:
        await self._check_session_timeout()
        if not self._host:
            await self._get_host()
        resp = await self._get("CREATE_SESSION")
        qid = resp.get("data", {}).get("qid")
        if not qid:
            raise MIPCError("Missing qid in session response")
        self._qid = qid
        return qid

    async def _do_dh(self) -> str:
        await self._check_session_timeout()
        if not self._qid:
            await self._get_qid()
        resp = await self._get("KEY", params={
            "dbnum_prime": PRIME,
            "dkey_a2b": self._public,
            "droot_num": ROOT_NUM,
        })
        self._key = resp.get("data", {}).get("key_b2a")
        self._lid = resp.get("data", {}).get("lid")
        if not self._key or not self._lid:
            raise MIPCError("Missing DH fields in response")
        self._shared_key = _gen_shared_secret(self._private, self._key)
        return self._key

    async def _do_auth(self, _in_retry: bool = False) -> str:
        await self._check_session_timeout()
        if not self._shared_key:
            await self._do_dh()
        self._encrypted_password = encrypt(self._password, self._shared_key)
        self._nid = _build_nid(self._seq, self._lid, self._shared_key, 2)
        resp = await self._get("LOGIN", params={
            "hqid": self._qid,
            "dlid": self._lid,
            "dnid": self._nid,
            "duser": self._username,
            "dpass": self._encrypted_password,
            "dsession_req": 1,
        })
        sid = resp.get("data", {}).get("sid")
        if not sid:
            raise MIPCError("Authentication failed: missing sid")
        self._sid = sid
        log.info("MIPC authentication successful")
        return sid

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def authenticate(self) -> None:
        """Authenticate from scratch. Call this on startup."""
        await self._retry("_do_auth")

    async def get_devices(self) -> list[dict]:
        """Return list of camera dicts from the MIPC account."""
        if not self._nid:
            await self._retry("_do_auth")
        resp = await self._get("DEVICES", params={
            "hqid": self._qid,
            "dsess": 1,
            "dsess_nid": self._nid,
            "dstart": 0,
            "dcounts": 1024,
        })
        return resp.get("data", {}).get("devs", [])

    async def get_stream_url(self, device_sn: str) -> str:
        """Return the RTSP stream URL for the given device serial number."""
        if not self._sid:
            await self._retry("_do_auth")
        nid = _build_nid(self._seq, self._sid, self._shared_key, 0)
        resp = await self._get("PLAY", params={
            "hqid": self._qid,
            "dsess": 1,
            "dsess_nid": nid,
            "dsess_sn": device_sn,
            "dsetup": 1,
            "dsetup_stream": "RTSP",
            "dsetup_trans": 1,
            "dsetup_trans_proto": "rtsp",
            "dtoken": "p0",
        })
        uri = resp.get("data", {}).get("MediaUri", {}).get("Uri")
        if not uri:
            raise MIPCError(f"No MediaUri in PLAY response for {device_sn}")

        token = self._extract_token(uri)
        if token and token.startswith("p0"):
            self._device_tokens[device_sn] = f"p1{token[2:]}"

        log.debug("Stream URL for %s: %s", device_sn, uri)
        return uri

    async def get_snapshot(self, device_sn: str) -> bytes:
        """Return raw JPEG bytes for a still image from the camera."""
        if not self._sid:
            await self._retry("_do_auth")

        # Refresh token
        await self.get_stream_url(device_sn)

        nid = _build_nid(self._seq, self._sid, self._shared_key, 0)
        url = self._url("STILL_IMAGE", {
            "dsess": 1,
            "dsess_nid": nid,
            "dsess_sn": device_sn,
            "dtoken": self._device_tokens.get(device_sn, "p1_xxxxxxxxxx"),
            "dencode_type": 0,
            "dpic_types_support": 2,
            "dflag": 2,
        })
        loop = asyncio.get_running_loop()
        response: Response = await loop.run_in_executor(None, _sync_get, url)
        try:
            return response.content
        finally:
            _close_response(response)

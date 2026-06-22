"""
Web UI for mipc-to-onvif configuration and status.
Runs on a dedicated port (default 8080).
"""

import asyncio
import json
import logging
import socket
from pathlib import Path

import yaml
from aiohttp import web

from state import ProxyState
from mipc.account import MIPCAccount, MIPCError

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML page (single-page, no external dependencies)
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MIPC to ONVIF Proxy</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #0f1117; color: #e2e8f0; min-height: 100vh; padding: 2rem 1rem; }
  h1 { font-size: 1.5rem; font-weight: 700; color: #fff; }
  h2 { font-size: 1.05rem; font-weight: 600; color: #94a3b8; text-transform: uppercase;
       letter-spacing: .06em; margin-bottom: 1rem; }
  .header { display: flex; align-items: center; gap: .75rem; margin-bottom: 2rem; }
  .logo { width: 2.2rem; height: 2.2rem; background: #3b82f6; border-radius: .5rem;
          display: flex; align-items: center; justify-content: center; font-size: 1.2rem; }
  .layout { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; max-width: 960px; margin: 0 auto; }
  @media (max-width: 640px) { .layout { grid-template-columns: 1fr; } }
  .card { background: #1e2130; border: 1px solid #2d3148; border-radius: .75rem; padding: 1.5rem; }
  .card.full { grid-column: 1 / -1; }
  label { display: block; font-size: .85rem; color: #94a3b8; margin-bottom: .35rem; margin-top: 1rem; }
  label:first-of-type { margin-top: 0; }
  input[type=text], input[type=password], input[type=number] {
    width: 100%; padding: .55rem .75rem; background: #0f1117; border: 1px solid #2d3148;
    border-radius: .4rem; color: #e2e8f0; font-size: .9rem; outline: none; transition: border .15s; }
  input:focus { border-color: #3b82f6; }
  .hint { font-size: .78rem; color: #64748b; margin-top: .3rem; }
  .row { display: flex; gap: .75rem; }
  .row > * { flex: 1; }
  .actions { display: flex; gap: .75rem; margin-top: 1.5rem; flex-wrap: wrap; }
  button { padding: .55rem 1.1rem; border: none; border-radius: .4rem; font-size: .88rem;
           font-weight: 600; cursor: pointer; transition: opacity .15s; }
  button:hover { opacity: .85; }
  button:disabled { opacity: .4; cursor: not-allowed; }
  .btn-primary { background: #3b82f6; color: #fff; }
  .btn-secondary { background: #2d3148; color: #e2e8f0; }
  .btn-danger { background: #dc2626; color: #fff; }
  .status-dot { width: .6rem; height: .6rem; border-radius: 50%; display: inline-block; margin-right: .45rem; }
  .dot-green { background: #22c55e; box-shadow: 0 0 6px #22c55e80; }
  .dot-red { background: #ef4444; }
  .dot-gray { background: #475569; }
  .status-row { display: flex; align-items: center; font-size: .9rem; margin-bottom: .5rem; }
  table { width: 100%; border-collapse: collapse; font-size: .88rem; }
  th { text-align: left; color: #64748b; font-weight: 600; font-size: .78rem;
       text-transform: uppercase; letter-spacing: .05em; padding: .4rem .6rem; border-bottom: 1px solid #2d3148; }
  td { padding: .55rem .6rem; border-bottom: 1px solid #1a1f2e; color: #cbd5e1; }
  tr:last-child td { border-bottom: none; }
  .badge { display: inline-block; padding: .15rem .5rem; border-radius: 9999px; font-size: .75rem; font-weight: 600; }
  .badge-green { background: #14532d; color: #4ade80; }
  .badge-gray  { background: #1e293b; color: #94a3b8; }
  .toast { position: fixed; top: 1rem; right: 1rem; padding: .75rem 1.25rem; border-radius: .5rem;
           font-size: .88rem; font-weight: 500; opacity: 0; transition: opacity .3s; pointer-events: none; z-index: 999; }
  .toast.show { opacity: 1; }
  .toast-ok  { background: #14532d; color: #4ade80; border: 1px solid #166534; }
  .toast-err { background: #450a0a; color: #f87171; border: 1px solid #7f1d1d; }
  .toast-info { background: #1e3a5f; color: #93c5fd; border: 1px solid #1e40af; }
  code { background: #0f1117; border: 1px solid #2d3148; border-radius: .3rem;
         padding: .1rem .4rem; font-size: .82rem; color: #7dd3fc; }
  .empty { color: #475569; font-size: .88rem; text-align: center; padding: 1.5rem 0; }
  .last-refresh { color: #475569; font-size: .78rem; margin-top: .75rem; }
  .section-title-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
</style>
</head>
<body>

<div style="max-width:960px; margin:0 auto">
  <div class="header">
    <div class="logo">&#x1F4F7;</div>
    <div>
      <h1>MIPC &rarr; ONVIF Proxy</h1>
      <div style="font-size:.82rem;color:#64748b">Translate MIPC cloud cameras into ONVIF for your NVR</div>
    </div>
  </div>

  <div class="layout">

    <!-- Status card -->
    <div class="card">
      <div class="section-title-row">
        <h2>Status</h2>
        <button class="btn-secondary" style="padding:.3rem .7rem;font-size:.78rem" onclick="refreshStatus()">Refresh</button>
      </div>
      <div id="status-body"><div class="empty">Loading&hellip;</div></div>
      <div class="last-refresh" id="last-refresh"></div>
    </div>

    <!-- Camera table card -->
    <div class="card">
      <h2>Cameras</h2>
      <div id="cameras-body"><div class="empty">No cameras detected yet.</div></div>
    </div>

    <!-- Settings form card -->
    <div class="card full">
      <h2>Configuration</h2>
      <form id="cfg-form" onsubmit="return false">

        <h2 style="margin-top:0;margin-bottom:.5rem">MIPC Account</h2>
        <div class="row">
          <div>
            <label for="username">Username <span style="color:#ef4444">*</span></label>
            <input id="username" name="username" type="text" placeholder="email or phone" autocomplete="username">
          </div>
          <div>
            <label for="password">Password <span style="color:#ef4444">*</span></label>
            <input id="password" name="password" type="password" autocomplete="current-password">
          </div>
        </div>

        <h2 style="margin-top:1.5rem;margin-bottom:.5rem">Network</h2>
        <div class="row">
          <div>
            <label for="host_ip">Host IP <span style="color:#ef4444">*</span></label>
            <input id="host_ip" name="host_ip" type="text" placeholder="192.168.1.100">
            <div class="hint">IP of the machine running Docker — must be reachable from your NVR</div>
          </div>
          <div>
            <label for="onvif_base_port">ONVIF base port</label>
            <input id="onvif_base_port" name="onvif_base_port" type="number" value="8080" min="1024" max="65000">
            <div class="hint">Camera 1 = this port, camera 2 = this port + 1, &hellip;</div>
          </div>
        </div>
        <div class="row" style="margin-top:.25rem">
          <div>
            <label for="rtsp_port">RTSP port (mediamtx)</label>
            <input id="rtsp_port" name="rtsp_port" type="number" value="8554" min="1024" max="65000">
          </div>
          <div></div>
        </div>

        <div class="actions">
          <button class="btn-secondary" type="button" id="btn-test" onclick="testConnection()">Test connection</button>
          <button class="btn-primary"   type="button" id="btn-save" onclick="saveConfig()">Save &amp; apply</button>
        </div>
      </form>
    </div>

    <!-- NVR instructions card -->
    <div class="card full" id="nvr-instructions" style="display:none">
      <h2>Add cameras to your NVR</h2>
      <p style="color:#94a3b8;font-size:.9rem;margin-bottom:1rem">
        In your Hikvision NVR go to <strong>Camera Management &rarr; Add</strong> and use:
      </p>
      <table>
        <thead><tr><th>Camera</th><th>Protocol</th><th>IP</th><th>ONVIF Port</th><th>RTSP URL</th></tr></thead>
        <tbody id="nvr-table-body"></tbody>
      </table>
      <p style="color:#64748b;font-size:.8rem;margin-top:.75rem">Username and password can be anything — auth is not enforced on the local ONVIF service.</p>
    </div>

  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let _statusPoll = null;

async function refreshStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    renderStatus(d);
  } catch(e) {
    showToast('Could not reach API', 'err');
  }
}

function renderStatus(d) {
  const sb = document.getElementById('status-body');
  const dot = d.connected ? 'dot-green' : (d.error ? 'dot-red' : 'dot-gray');
  const label = d.connected ? 'Connected' : (d.error || 'Not connected');
  sb.innerHTML = `<div class="status-row"><span class="status-dot ${dot}"></span>${escHtml(label)}</div>`;

  const cb = document.getElementById('cameras-body');
  if (!d.cameras || d.cameras.length === 0) {
    cb.innerHTML = '<div class="empty">No cameras detected yet.</div>';
    document.getElementById('nvr-instructions').style.display = 'none';
  } else {
    cb.innerHTML = `<table>
      <thead><tr><th>Camera</th><th>Status</th><th>ONVIF port</th></tr></thead>
      <tbody>${d.cameras.map(c => `
        <tr>
          <td><code style="font-size:.75rem">${escHtml(c.sn)}</code></td>
          <td><span class="badge ${c.online ? 'badge-green' : 'badge-gray'}">${c.online ? 'Online' : 'Offline'}</span></td>
          <td>${c.onvif_port}</td>
        </tr>`).join('')}
      </tbody></table>`;

    const nvrTbody = document.getElementById('nvr-table-body');
    const hostIp = d.host_ip || '&lt;host_ip&gt;';
    nvrTbody.innerHTML = d.cameras.map(c => `
      <tr>
        <td><code style="font-size:.75rem">${escHtml(c.sn)}</code></td>
        <td>ONVIF</td>
        <td>${hostIp}</td>
        <td>${c.onvif_port}</td>
        <td><code>rtsp://${hostIp}:${d.rtsp_port || 8554}/${escHtml(c.sn)}</code></td>
      </tr>`).join('');
    document.getElementById('nvr-instructions').style.display = '';
  }

  if (d.last_refresh) {
    document.getElementById('last-refresh').textContent = 'Last refresh: ' + d.last_refresh;
  }
}

async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    const d = await r.json();
    if (d.username)        document.getElementById('username').value        = d.username;
    if (d.password)        document.getElementById('password').value        = d.password;
    if (d.host_ip)         document.getElementById('host_ip').value         = d.host_ip;
    if (d.onvif_base_port) document.getElementById('onvif_base_port').value = d.onvif_base_port;
    if (d.rtsp_port)       document.getElementById('rtsp_port').value       = d.rtsp_port;
  } catch(e) { /* ignore on first load */ }
}

async function testConnection() {
  const body = collectForm();
  if (!body.username || !body.password) { showToast('Username and password are required', 'err'); return; }
  setBusy(true);
  showToast('Testing connection…', 'info');
  try {
    const r = await fetch('/api/test', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const d = await r.json();
    if (d.ok) {
      showToast(`Connected — found ${d.cameras.length} camera(s)`, 'ok');
    } else {
      showToast('Error: ' + (d.error || 'unknown'), 'err');
    }
  } catch(e) {
    showToast('Request failed', 'err');
  } finally {
    setBusy(false);
  }
}

async function saveConfig() {
  const body = collectForm();
  if (!body.username || !body.password) { showToast('Username and password are required', 'err'); return; }
  if (!body.host_ip) { showToast('Host IP is required', 'err'); return; }
  setBusy(true);
  showToast('Saving…', 'info');
  try {
    const r = await fetch('/api/save', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const d = await r.json();
    if (d.ok) {
      showToast('Saved — reinitialising cameras…', 'ok');
      setTimeout(refreshStatus, 3000);
    } else {
      showToast('Error: ' + (d.error || 'unknown'), 'err');
    }
  } catch(e) {
    showToast('Request failed', 'err');
  } finally {
    setBusy(false);
  }
}

function collectForm() {
  return {
    username:        document.getElementById('username').value.trim(),
    password:        document.getElementById('password').value,
    host_ip:         document.getElementById('host_ip').value.trim(),
    onvif_base_port: parseInt(document.getElementById('onvif_base_port').value, 10) || 8080,
    rtsp_port:       parseInt(document.getElementById('rtsp_port').value, 10) || 8554,
  };
}

function setBusy(b) {
  document.getElementById('btn-test').disabled = b;
  document.getElementById('btn-save').disabled = b;
}

function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.className = `toast toast-${type} show`;
  t.textContent = msg;
  clearTimeout(t._tid);
  t._tid = setTimeout(() => { t.className = 'toast'; }, 3500);
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Init
loadConfig();
refreshStatus();
_statusPoll = setInterval(refreshStatus, 10000);
</script>
</body>
</html>
"""


def _detect_local_ip() -> str:
    """Best-effort detection of the host-facing IP (useful as a starting hint)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return ""


class WebUIServer:
    def __init__(
        self,
        *,
        port: int,
        config_path: str,
        state: "ProxyState",
    ) -> None:
        self._port = port
        self._config_path = Path(config_path)
        self._state = state
        self._runner: web.AppRunner | None = None

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _read_config(self) -> dict:
        if not self._config_path.exists():
            return {}
        with open(self._config_path) as f:
            return yaml.safe_load(f) or {}

    def _write_config(self, data: dict) -> None:
        cfg = self._read_config()
        cfg.setdefault("mipc", {})["username"] = data["username"]
        cfg["mipc"]["password"] = data["password"]
        cfg.setdefault("proxy", {})["host_ip"] = data["host_ip"]
        cfg["proxy"]["onvif_base_port"] = data["onvif_base_port"]
        cfg["proxy"]["rtsp_port"] = data["rtsp_port"]
        cfg["proxy"].setdefault("mediamtx_api", "http://mediamtx:9997")
        with open(self._config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

    def _config_for_client(self) -> dict:
        cfg = self._read_config()
        return {
            "username": cfg.get("mipc", {}).get("username", ""),
            "password": cfg.get("mipc", {}).get("password", ""),
            "host_ip": cfg.get("proxy", {}).get("host_ip", _detect_local_ip()),
            "onvif_base_port": cfg.get("proxy", {}).get("onvif_base_port", 8081),
            "rtsp_port": cfg.get("proxy", {}).get("rtsp_port", 8554),
        }

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------

    async def _handle_index(self, _: web.Request) -> web.Response:
        return web.Response(body=_HTML.encode(), content_type="text/html")

    async def _handle_api_config(self, _: web.Request) -> web.Response:
        return web.json_response(self._config_for_client())

    async def _handle_api_status(self, _: web.Request) -> web.Response:
        s = self._state
        cfg = self._read_config()
        return web.json_response({
            "connected": s.connected,
            "error": s.error,
            "cameras": [
                {
                    "sn": c.sn,
                    "name": c.name,
                    "online": c.online,
                    "onvif_port": c.onvif_port,
                    "rtsp_path": c.rtsp_path,
                }
                for c in s.cameras
            ],
            "last_refresh": s.last_refresh.isoformat() if s.last_refresh else None,
            "host_ip": cfg.get("proxy", {}).get("host_ip", ""),
            "rtsp_port": cfg.get("proxy", {}).get("rtsp_port", 8554),
        })

    async def _handle_api_test(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

        username = data.get("username", "").strip()
        password = data.get("password", "")
        if not username or not password:
            return web.json_response({"ok": False, "error": "Username and password required"})

        account = MIPCAccount(username=username, password=password)
        try:
            await account.authenticate()
            devices = await account.get_devices()
            return web.json_response({
                "ok": True,
                "cameras": [{"sn": d["sn"], "online": d.get("stat") == "Online"} for d in devices],
            })
        except MIPCError as err:
            return web.json_response({"ok": False, "error": str(err)})
        except Exception as err:
            return web.json_response({"ok": False, "error": f"Unexpected error: {err}"})

    async def _handle_api_save(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

        required = ("username", "password", "host_ip", "onvif_base_port", "rtsp_port")
        for k in required:
            if k not in data:
                return web.json_response({"ok": False, "error": f"Missing field: {k}"})

        try:
            self._write_config(data)
            log.info("Config saved by web UI")
        except Exception as err:
            return web.json_response({"ok": False, "error": f"Could not write config: {err}"})

        # Trigger re-initialisation in the background (non-blocking)
        if self._state.reinit_callback:
            asyncio.create_task(self._state.reinit_callback())

        return web.json_response({"ok": True})

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/",           self._handle_index)
        app.router.add_get("/api/config", self._handle_api_config)
        app.router.add_get("/api/status", self._handle_api_status)
        app.router.add_post("/api/test",  self._handle_api_test)
        app.router.add_post("/api/save",  self._handle_api_save)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._port)
        await site.start()
        log.info("Web UI listening on http://0.0.0.0:%d", self._port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

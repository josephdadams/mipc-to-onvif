# mipc-to-onvif

Translates MIPC cloud cameras into ONVIF-compatible cameras so any ONVIF-capable NVR (Hikvision, Dahua, Reolink, Blue Iris, etc.) can stream and record them.

MIPC cameras authenticate through the MIPC cloud service (mipcm.com) rather than exposing a standard RTSP or ONVIF interface directly. This proxy sits between your NVR and the cloud: it handles all MIPC authentication, proxies the video stream locally via [mediamtx](https://github.com/bluenviron/mediamtx), and presents each camera as an ONVIF device on its own port.

---

## How it works

```
NVR
 └─ ONVIF (port 8080, 8081, …)
     └─ mipc-proxy  ←→  MIPC cloud (mipcm.com)
         └─ mediamtx RTSP relay (port 8554)
             └─ NVR pulls RTSP stream
```

1. **MIPC authentication** — on startup the proxy performs a Diffie-Hellman key exchange with the MIPC signalling server, encrypts your password with the derived key, and logs in to obtain a session token.
2. **Device discovery** — the proxy fetches the list of cameras on your account and retrieves a cloud RTSP URL (with a short-lived token) for each one.
3. **RTSP relay** — each camera's cloud RTSP URL is registered as a path in mediamtx. mediamtx pulls the stream from MIPC and re-serves it locally on `rtsp://<your-host>:8554/<camera-serial>`. Tokens are refreshed every 5 minutes.
4. **ONVIF server** — each camera gets a minimal ONVIF Device + Media service running on its own port (8080 for the first camera, 8081 for the second, etc.). When your NVR queries for the stream URI, it receives the local mediamtx RTSP URL.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) (v2)
- A MIPC account with at least one camera added ([mipcm.com](http://www.mipcm.com))
- Your NVR must be able to reach the machine running Docker over the network

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/josephdadams/mipc-to-onvif.git
cd mipc-to-onvif
```

### 2. Create a config file

```bash
cp config.example.yml config.yml
```

You can leave `config.yml` empty and configure everything through the web UI, or fill it in now:

```yaml
mipc:
  username: "your@email.com"   # MIPC account username
  password: "yourpassword"

proxy:
  host_ip: 192.168.1.100       # IP of the machine running Docker
  onvif_base_port: 8081
  rtsp_port: 8554
  web_port: 8080
  mediamtx_api: http://mediamtx:9997
```

> **`host_ip` is important.** This is the IP address your NVR uses to reach the Docker host — not the container's IP. Set it to whatever IP address the Docker host has on your local network.

### 3. Start the containers

```bash
docker compose up -d
```

On first run Docker will build the proxy image, which takes a minute or two.

### 4. Open the web UI

Navigate to `http://<host-ip>:8080` in a browser.

If you left `config.yml` empty, enter your MIPC credentials and host IP here. Click **Test connection** to verify the credentials work and see how many cameras are found, then **Save & apply** to start the proxy.

The status panel updates automatically. Once cameras appear as detected, proceed to add them to your NVR.

---

## Adding cameras to your NVR

Each camera is exposed as a separate ONVIF device. The web UI shows the exact port for each camera under the **Add cameras to your NVR** section, but the general pattern is:

| Camera | Protocol | IP | Port |
|--------|----------|----|------|
| First camera | ONVIF | `<host_ip>` | 8081 |
| Second camera | ONVIF | `<host_ip>` | 8082 |
| Third camera | ONVIF | `<host_ip>` | 8083 |
| … | | | |

**Username and password:** the ONVIF service does not enforce authentication — enter any value in your NVR.

### Hikvision NVR

1. Go to **Camera Management → Add**
2. Select **Add by IP/Domain**
3. Set protocol to **ONVIF**
4. Enter the host IP and the camera's ONVIF port
5. Enter any username/password
6. Click **Add**

### Blue Iris

1. Add a new camera → **Network IP**
2. Protocol: **ONVIF**
3. Address: `<host_ip>:<port>`
4. Any username/password

### Generic ONVIF NVR

Point the camera at `http://<host_ip>:<port>/onvif/device_service`. Any ONVIF-compliant device should discover the stream automatically.

---

## Configuration reference

| Key | Default | Description |
|-----|---------|-------------|
| `mipc.username` | — | MIPC account email or phone number |
| `mipc.password` | — | MIPC account password |
| `proxy.host_ip` | — | LAN IP of the Docker host, reachable from the NVR |
| `proxy.onvif_base_port` | `8081` | ONVIF port for the first camera; each subsequent camera increments by 1 |
| `proxy.rtsp_port` | `8554` | Port mediamtx serves RTSP on |
| `proxy.web_port` | `8080` | Port for the configuration web UI |
| `proxy.mediamtx_api` | `http://mediamtx:9997` | Internal mediamtx API URL (no need to change) |

Changes made through the web UI are written to `config.yml` and applied immediately without restarting the container.

---

## Port reference

| Port | Protocol | Purpose |
|------|----------|---------|
| 8080 | HTTP | Web UI |
| 8554 | RTSP | mediamtx stream relay (NVR connects here) |
| 8081 | HTTP/SOAP | ONVIF — camera 1 |
| 8082 | HTTP/SOAP | ONVIF — camera 2 |
| 8083 | HTTP/SOAP | ONVIF — camera 3 |
| … | | |

> If you have more than 10 cameras, extend the port range in `docker-compose.yml`:
> ```yaml
> ports:
>   - "8081-8110:8081-8110"
> ```

---

## Updating

```bash
docker compose pull          # pull latest mediamtx
docker compose build         # rebuild the proxy image
docker compose up -d         # restart with new images
```

---

## Troubleshooting

**Web UI shows "Not connected" after saving credentials**
- Check the container logs: `docker compose logs -f mipc-proxy`
- Verify your MIPC username and password work in the MIPC mobile app
- The MIPC API uses several fallback hosts on startup — a slow first connection can take 15–20 seconds

**NVR can't connect to the ONVIF service**
- Confirm `host_ip` in `config.yml` is the LAN IP of the Docker host, not `127.0.0.1` or a container IP
- Make sure the ONVIF ports (8080+) are not blocked by a firewall on the Docker host
- Try `curl http://<host_ip>:8080/onvif/device_service` from another machine — you should get an XML response

**Stream connects but video doesn't play**
- Check mediamtx logs: `docker compose logs -f mipc-mediamtx`
- The MIPC cloud RTSP URL contains a short-lived token. If the NVR waits too long to start streaming after the ONVIF handshake, the token may have expired. RTSP tokens are refreshed every 5 minutes automatically.

**Camera shows as offline in the web UI**
- The camera may be powered off or unreachable from the MIPC cloud
- ONVIF and RTSP paths are still created for offline cameras; they will start streaming automatically once the camera comes back online and the next token refresh runs (up to 5 minutes)

---

## Project structure

```
mipc-to-onvif/
├── docker-compose.yml
├── Dockerfile
├── mediamtx.yml          # mediamtx configuration
├── config.example.yml    # copy to config.yml
├── requirements.txt
└── src/
    ├── main.py           # orchestrator — auth, camera init, refresh loop
    ├── config.py         # config file loader
    ├── state.py          # shared runtime state
    ├── mipc/
    │   ├── account.py    # MIPC cloud API client
    │   ├── const.py      # API endpoints and constants
    │   └── crypto.py     # DH key exchange + DES password encryption
    ├── onvif/
    │   ├── server.py     # per-camera ONVIF HTTP server (aiohttp)
    │   └── soap.py       # SOAP XML request parsing and response generation
    ├── rtsp/
    │   └── manager.py    # mediamtx HTTP API client
    └── web/
        └── server.py     # configuration and status web UI
```

---

## Credits

MIPC protocol implementation adapted from [battler2006/homeassistant-mipc-camera](https://github.com/battler2006/homeassistant-mipc-camera).

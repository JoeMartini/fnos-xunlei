# fnos-xunlei — 飞牛 fnOS 迅雷 OpenCLI Adapter

[OpenCLI](https://github.com/jackwener/opencli) adapter for the Xunlei (迅雷) download app built into [fnOS](https://www.fnos.com/) (飞牛 NAS). Pure HTTP — no browser, no CDP, no Chrome required for ongoing use.

## Features

- **Pure HTTP** — calls the Xunlei REST API directly, no browser/CDP dependency
- **Auto token refresh** — three-tier fallback (cache → browser bridge → WebSocket)
- **OpenCLI LOCAL strategy** — `browser: false`, starts instantly
- **Zero hardcoded values** — device_id and folder_id auto-discovered on first run
- **Full task lifecycle** — list, add, pause, resume, get link, delete

## Install

```bash
# 1. Install Python dependencies
pip install requests websocket-client
# Optional (for WebSocket token refresh with RSA):
pip install cryptography

# 2. Copy adapter to OpenCLI clis directory
cp -r clis/fnos-xunlei ~/.opencli/clis/

# 3. Copy backend script
mkdir -p ~/.local/share/fnos-xunlei
cp scripts/xunlei_http.py ~/.local/share/fnos-xunlei/
```

Or place `xunlei_http.py` next to the adapters in `~/.opencli/clis/fnos-xunlei/scripts/`.

## First-time setup

The initial token extraction requires a logged-in fnOS browser session. On a **desktop** this is straightforward — on a **headless server or NAS** without GUI, see [Headless environment setup](#headless-environment-setup) below.

### Desktop (has browser)

1. Log in to your fnOS Web UI (`http://YOUR_NAS_IP:5666/`) in Chrome
2. Run the init command (extracts token from browser, discovers device info):

```bash
python3 ~/.local/share/fnos-xunlei/xunlei_http.py init
```

3. Done! No browser needed after this — all subsequent calls are pure HTTP.

### Headless environment setup

Most NAS and VPS servers don't have a GUI. Without a browser, you can't log in to fnOS Web UI directly. **[remote-chromium](https://github.com/JoeMartini/remote-chromium)** solves this — it provides a containerized Chromium with KasmVNC web desktop and CDP endpoint on headless Linux:

1. **Deploy remote-chromium** on your server (or any machine that can reach the NAS):

```bash
# One-line deploy: Docker + KasmVNC + Chromium + CDP on port 9224
curl -fsSL https://raw.githubusercontent.com/JoeMartini/remote-chromium/main/scripts/quickstart.sh | bash
cd ~/remote-chromium && ./scripts/start.sh
```

2. **Log in to fnOS** through the remote Chromium web desktop:
   - Open `https://your-server:50443/` in your local browser
   - In the remote Chromium, navigate to `http://YOUR_NAS_IP:5666/` and log in to fnOS

3. **Run init** — the script will auto-detect the remote Chromium via CDP (`localhost:9222` or `localhost:9224`) and extract the token:

```bash
python3 ~/.local/share/fnos-xunlei/xunlei_http.py init
```

4. **Token persisted** — after this one-time setup, all calls are pure HTTP. The remote Chromium can be stopped; it's only needed again when `fnos-long-token` expires (30 days).

> **Alternative without remote-chromium:** If you have a desktop machine on the same network, run `init` there (it will extract the token from your local Chrome), then copy `~/.config/fnos-xunlei/token.json` to the headless server.

## Usage

### OpenCLI commands

```bash
opencli fnos-xunlei list [--limit 10]                 # List tasks (with speed)
opencli fnos-xunlei add "magnet:?xt=urn:btih:..."      # Add magnet download
opencli fnos-xunlei pause <task_id>                    # Pause a task
opencli fnos-xunlei resume <task_id>                   # Resume a paused task
opencli fnos-xunlei link <task_id>                     # Get original download URL (复制链接)
opencli fnos-xunlei delete <task_id>                   # Delete task (and files)
opencli fnos-xunlei delete <task_id> --keepFiles       # Delete task, keep files
```

Output formats: `-f json`, `-f yaml`, `-f table` (default), `-f csv`

### Python backend directly

```bash
python3 xunlei_http.py init                    # Discover device_id & folder_id
python3 xunlei_http.py list [--limit N] [--json]  # List tasks (with speed)
python3 xunlei_http.py add <magnet>            # Add download
python3 xunlei_http.py pause <task_id>         # Pause task
python3 xunlei_http.py resume <task_id>        # Resume task
python3 xunlei_http.py link <task_id>          # Print original download URL
python3 xunlei_http.py delete <task_id> [--keep-files]  # Delete task
python3 xunlei_http.py auth                    # Show token status
```

## How it works

### Authentication chain

```
fnos-token (fnOS login session)
  └→ pan_auth (UIAuth JWT, 72h) — extracted from Xunlei page HTML
```

The key insight from reverse-engineering: the fnOS CGI proxy validates `fnos-token` directly. The `xtoken` (60s cookie) that the browser SPA refreshes is **not** required for HTTP calls.

### Token refresh (three-tier fallback)

| Tier | Trigger | Method |
|------|---------|--------|
| 1. Cache | Default | Read `~/.config/fnos-xunlei/token.json`, verify via HTTP |
| 2. Browser bridge | Cache expired + Chrome running | CDP extracts fresh fnos-token + fnos-long-token, auto-detects port from tab URL |
| 3. WebSocket | No browser + has fnos-long-token | WS `user.tokenLogin` refreshes via 30-day long-token |

| Token | Validity | Source |
|-------|----------|--------|
| fnos-long-token | 30 days | fnOS login |
| fnos-token | Days (session) | long-token refresh |
| pan_auth | 72 hours | Auto-extracted from HTML each run |

### API endpoints

| Operation | Method | Endpoint |
|-----------|--------|----------|
| List tasks | GET | `/drive/v1/tasks` |
| Parse magnet | POST | `/drive/v1/resource/list` |
| Create task | POST | `/drive/v1/task` |
| Pause/Resume task | PATCH | `/drive/v1/task` (with `set_params.spec={"phase":"pause"}` or `"running"`) |
| Get task link | — | `params.url` field from task list (no separate API) |
| Delete task | POST | `/method/delete/drive/v1/tasks` |
| Discover device | GET | `/drive/v1/tasks?type=user#runner` |
| Download paths | GET | `/device/download_paths` |

Pause/resume uses `PATCH /drive/v1/task` with `set_params.spec = {"phase": "pause"}` (or `"running"` for resume). This API pattern was reverse-engineered from the Xunlei SPA's JavaScript.

The "复制链接" (copy link) feature reads the original magnet/HTTP URL from the task's `params.url` field — no separate API endpoint needed.

All endpoints are under `http://NAS_IP:5666/cgi/ThirdParty/xunlei/index.cgi`.

## Configuration

Config file: `~/.config/fnos-xunlei/token.json` (permissions 0600)

```json
{
  "fnos_token": "...",
  "fnos_long_token": "...",
  "nas_ip": "192.168.1.100",
  "fnos_port": 5666,
  "device_id": "device_id#...",
  "folder_id": "...",
  "folder_path": "/path/to/downloads/"
}
```

All fields except `nas_ip` and `fnos_port` are auto-discovered by `init`. No hardcoded values. Default port is 5666 (fnOS V0.8.22+); set `fnos_port` in config if your NAS uses a custom port. The browser bridge also auto-detects the port from the Chrome tab URL.

## Architecture

```
clis/fnos-xunlei/
├── _shared.js     # resolveBackend() + runBackend()
├── list.js        # List tasks (with speed)
├── add.js         # Add magnet download
├── pause.js       # Pause task
├── resume.js      # Resume task
├── link.js        # Get original download URL
└── delete.js      # Delete task

scripts/
└── xunlei_http.py  # Python backend (auth + API calls)
```

JS adapters handle argument validation and output formatting. All auth and API logic lives in the Python backend — single source of truth, no JS reimplementation.

## Related projects

- **[remote-chromium](https://github.com/JoeMartini/remote-chromium)** — Headless Linux Chromium container (KasmVNC + CDP). Provides the browser environment needed for the one-time fnOS login on servers without GUI.
- **[OpenCLI](https://github.com/jackwener/opencli)** — CLI framework that this adapter targets. Supports LOCAL, COOKIE, INTERCEPT, and UI strategies.

## Limitations

- Xunlei free tier: 3 download tasks per day (non-member limit)
- "Delete local files" is unreliable — verify and `rm -rf` manually if needed
- WebSocket token refresh (RSA path) is implemented but not fully tested against all fnOS versions

## License

MIT

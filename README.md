# fnos-xunlei — 飞牛 fnOS 迅雷 OpenCLI Adapter

[OpenCLI](https://github.com/JackWener/opencli) adapter for the Xunlei (迅雷) download app built into [fnOS](https://www.fnos.com/) (飞牛 NAS). Pure HTTP — no browser, no CDP, no Chrome required.

## Features

- **Pure HTTP** — calls the Xunlei REST API directly, no browser/CDP dependency
- **Auto token refresh** — three-tier fallback (cache → browser bridge → WebSocket)
- **OpenCLI LOCAL strategy** — `browser: false`, starts instantly
- **Zero hardcoded values** — device_id and folder_id auto-discovered on first run

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

1. Log in to your fnOS Web UI (`http://YOUR_NAS_IP:5666/`) in Chrome
2. Run the init command (extracts token from browser, discovers device info):

```bash
python3 ~/.local/share/fnos-xunlei/xunlei_http.py init
```

3. Done! No browser needed after this.

## Usage

### OpenCLI commands

```bash
opencli fnos-xunlei list [--limit 10]           # List download tasks
opencli fnos-xunlei add "magnet:?xt=urn:btih:..."  # Add magnet download
opencli fnos-xunlei delete <task_id>             # Delete task (and files)
opencli fnos-xunlei delete <task_id> --keepFiles # Delete task, keep files
```

Output formats: `-f json`, `-f yaml`, `-f table` (default), `-f csv`

### Python backend directly

```bash
python3 xunlei_http.py init     # Discover device_id & folder_id
python3 xunlei_http.py list     # List tasks
python3 xunlei_http.py list --json  # JSON output for scripting
python3 xunlei_http.py add <magnet>
python3 xunlei_http.py delete <task_id> [--keep-files]
python3 xunlei_http.py auth     # Show token status
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
| 2. Browser bridge | Cache expired + Chrome running | CDP extracts fresh fnos-token + fnos-long-token |
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
| Delete task | POST | `/method/delete/drive/v1/tasks` |
| Discover device | GET | `/drive/v1/tasks?type=user#runner` |
| Download paths | GET | `/device/download_paths` |

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

All fields except `nas_ip` and `fnos_port` are auto-discovered by `init`. No hardcoded values. Default port is 5666 (fnOS V0.8.22+); set `fnos_port` in config if your NAS uses a custom port.

## Architecture

```
clis/fnos-xunlei/
├── _shared.js     # resolveBackend() + runBackend()
├── list.js        # Strategy.LOCAL, browser:false
├── add.js
└── delete.js

scripts/
└── xunlei_http.py  # Python backend (auth + API calls)
```

JS adapters handle argument validation and output formatting. All auth and API logic lives in the Python backend — single source of truth, no JS reimplementation.

## Limitations

- Xunlei free tier: 3 download tasks per day (non-member limit)
- "Delete local files" is unreliable — verify and `rm -rf` manually if needed
- WebSocket token refresh (RSA path) is implemented but not fully tested against all fnOS versions

## License

MIT

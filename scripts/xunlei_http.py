#!/usr/bin/env python3
"""
fnOS Xunlei HTTP Client — pure HTTP, no browser/CDP required.

Authentication:
  fnos-token (fnOS login session) → pan_auth (72h JWT, from HTML)

Token refresh chain:
  1. Cached fnos-token (verified via HTTP)
  2. Browser CDP bridge (if Chrome is running with fnOS tab)
  3. WebSocket tokenLogin (uses 30-day fnos-long-token)

Usage:
    xunlei_http.py list [--limit N] [--json]
    xunlei_http.py add <magnet>
    xunlei_http.py delete <task_id> [--keep-files]
    xunlei_http.py auth  # show pan_auth status
    xunlei_http.py init  # bootstrap: discover device_id & folder_id

Config: ~/.config/fnos-xunlei/token.json
    {
      "fnos_token": "...",
      "fnos_long_token": "...",
      "nas_ip": "192.168.x.x",
      "device_id": "device_id#...",
      "folder_id": "...",
      "folder_path": "/path/to/downloads/"
    }

First run: login to fnOS Web UI, then run `xunlei_http.py init`.
"""

import requests
import json
import re
import sys
import os
import time
import base64

CONFIG_DIR = os.path.expanduser("~/.config/fnos-xunlei")
CONFIG_FILE = os.path.join(CONFIG_DIR, "token.json")
DEFAULT_NAS_IP = "192.168.1.1"
FNOS_PORT = 5666  # fnOS default HTTP port (V0.8.22+), user can override via config


# ─── Config ───────────────────────────────────────────────────────────────────

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.chmod(CONFIG_FILE, 0o600)


# ─── Token management ─────────────────────────────────────────────────────────

def get_fnos_token():
    """Obtain a valid fnos-token via three-strategy fallback.

    Returns: (token, nas_ip, fnos_port)
    """
    cfg = load_config()
    nas_ip = cfg.get("nas_ip", DEFAULT_NAS_IP)
    fnos_port = cfg.get("fnos_port", FNOS_PORT)

    # Strategy 1: cached token (verify with a lightweight HTTP check)
    cached = cfg.get("fnos_token")
    if cached and _verify_token(cached, nas_ip, fnos_port):
        return cached, nas_ip, fnos_port
    if cached:
        print("[auth] Cached fnos-token expired, trying refresh...", file=sys.stderr)

    # Strategy 2: browser CDP bridge (also picks up long-token for future use)
    bridge_token, bridge_long, bridge_ip, bridge_port = _bridge_from_browser(cfg)
    if bridge_token:
        cfg["fnos_token"] = bridge_token
        cfg["nas_ip"] = bridge_ip or nas_ip
        if bridge_port:
            cfg["fnos_port"] = bridge_port
        if bridge_long:
            cfg["fnos_long_token"] = bridge_long
        save_config(cfg)
        print("[auth] Refreshed fnos-token via browser bridge", file=sys.stderr)
        return bridge_token, cfg["nas_ip"], cfg.get("fnos_port", fnos_port)

    # Strategy 3: WebSocket tokenLogin with fnos-long-token
    long_token = cfg.get("fnos_long_token") or bridge_long
    if long_token:
        ws_ip = cfg.get("nas_ip", DEFAULT_NAS_IP)
        ws_port = cfg.get("fnos_port", FNOS_PORT)
        ws_token = _ws_token_login(long_token, ws_ip, ws_port)
        if ws_token:
            cfg["fnos_token"] = ws_token
            cfg["fnos_long_token"] = long_token
            cfg["nas_ip"] = ws_ip
            cfg["fnos_port"] = ws_port
            save_config(cfg)
            print("[auth] Refreshed fnos-token via WebSocket tokenLogin", file=sys.stderr)
            return ws_token, ws_ip, ws_port

    print("ERROR: Cannot obtain fnos-token.", file=sys.stderr)
    print(f"  Login to fnOS Web UI (http://{nas_ip}:{fnos_port}/) and re-run.", file=sys.stderr)
    sys.exit(1)


def _verify_token(token, nas_ip, fnos_port):
    """Quick HTTP check: does this fnos-token still work?"""
    try:
        resp = requests.get(
            f"http://{nas_ip}:{fnos_port}/cgi/ThirdParty/xunlei/index.cgi/",
            headers={"Cookie": f"fnos-token={token}"},
            timeout=5,
        )
        return "invalid token" not in resp.text
    except Exception:
        return False


def _bridge_from_browser(cfg):
    """Extract tokens from an open Chrome tab via CDP.

    Returns: (fnos_token, fnos_long_token, nas_ip, fnos_port) or (None, None, None, None)
    """
    try:
        import websocket
        import threading
        import queue
    except ImportError:
        return None, None, None, None

    nas_ip = cfg.get("nas_ip", DEFAULT_NAS_IP)
    fnos_port = cfg.get("fnos_port", FNOS_PORT)
    cdp_url = "http://127.0.0.1:9222"

    try:
        tabs = requests.get(f"{cdp_url}/json/list", timeout=3).json()
    except Exception:
        return None, None, None, None

    # Prefer a tab that's on the fnOS domain
    fnos_tabs = [t for t in tabs if nas_ip in t.get("url", "") or str(fnos_port) in t.get("url", "")]
    if not fnos_tabs:
        fnos_tabs = [t for t in tabs if t.get("type") == "page"]
    if not fnos_tabs:
        return None, None, None, None

    try:
        ws = websocket.create_connection(fnos_tabs[0]["webSocketDebuggerUrl"], timeout=5)
    except Exception:
        return None, None, None

    ws.settimeout(2)
    msg_q = queue.Queue()
    _next_id = [0]

    def _reader():
        while True:
            try:
                r = ws.recv()
                if r:
                    msg_q.put(json.loads(r))
            except Exception:
                break

    threading.Thread(target=_reader, daemon=True).start()

    def _cdp(method, params=None):
        _next_id[0] += 1
        mid = _next_id[0]
        msg = {"id": mid, "method": method}
        if params:
            msg["params"] = params
        ws.send(json.dumps(msg))
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                r = msg_q.get(timeout=0.5)
                if r.get("id") == mid:
                    return r
                # Put non-matching events back
                msg_q.put(r)
            except queue.Empty:
                pass
        return None

    result = _cdp("Network.getCookies", {"urls": [f"http://{nas_ip}:{fnos_port}/"]})
    ws.close()
    if not result:
        return None, None, None, None

    cookies = result.get("result", {}).get("cookies", [])
    fnos_token = None
    long_token = None
    for c in cookies:
        if c["name"] == "fnos-token":
            fnos_token = c["value"]
        elif c["name"] == "fnos-long-token":
            long_token = c["value"]

    return fnos_token, long_token, nas_ip, fnos_port


def _ws_token_login(long_token, nas_ip, fnos_port):
    """Refresh fnos-token via fnOS WebSocket (ws://IP:port/websocket?type=main).

    fnOS WS auth protocol:
      1. Client connects
      2. Server sends {"req": "util.crypto.getRSAPub", "pub": "<PEM>"} (RSA preflight)
      3. Client encrypts long_token with RSA public key, sends tokenLogin
      4. Server responds with {"token": "<fnos-token>", "result": "succ"}

    Falls back to plaintext tokenLogin if no RSA challenge received.
    """
    try:
        import websocket as ws_mod
    except ImportError:
        print("[auth] pip install websocket-client for WS refresh", file=sys.stderr)
        return None

    ws_url = f"ws://{nas_ip}:{fnos_port}/websocket?type=main"
    try:
        ws = ws_mod.create_connection(
            ws_url, timeout=10,
            header={"Origin": f"http://{nas_ip}:{fnos_port}"},
        )
    except Exception as e:
        print(f"[auth] WS connect failed: {e}", file=sys.stderr)
        return None

    try:
        ws.settimeout(5)
        # Read first message — may be RSA challenge or direct response
        first = json.loads(ws.recv())

        # RSA preflight: server sends getRSAPub
        if "pub" in first or first.get("req") == "util.crypto.getRSAPub":
            pub_pem = first.get("pub", "")
            if pub_pem:
                token_to_send = _rsa_encrypt(long_token, pub_pem)
            else:
                token_to_send = long_token
        else:
            # No RSA challenge — maybe we can send plaintext directly
            token_to_send = long_token

        # Send tokenLogin
        login_req = {
            "req": "user.tokenLogin",
            "reqid": f"{int(time.time()):x}",
            "token": token_to_send,
            "deviceType": "web",
            "deviceName": "fnos-xunlei-http",
            "did": "",
        }
        ws.send(json.dumps(login_req))

        # Read response
        resp = json.loads(ws.recv())

        # If first msg was RSA challenge, the response is to our login_req
        if "pub" in first:
            # Already sent login above, resp should be the answer
            pass
        else:
            # first msg might have been an unsolicited RSA challenge
            # Check if resp is another challenge
            if "pub" in resp:
                pub_pem = resp.get("pub", "")
                token_to_send = _rsa_encrypt(long_token, pub_pem) if pub_pem else long_token
                login_req["token"] = token_to_send
                ws.send(json.dumps(login_req))
                resp = json.loads(ws.recv())

        ws.close()

        if resp.get("token"):
            return resp["token"]
        print(f"[auth] WS tokenLogin failed: {resp}", file=sys.stderr)
        return None
    except Exception as e:
        try:
            ws.close()
        except Exception:
            pass
        print(f"[auth] WS error: {e}", file=sys.stderr)
        return None


def _rsa_encrypt(plaintext, pub_key_pem):
    """RSA-encrypt plaintext with the given PEM public key."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        print("[auth] pip install cryptography for RSA token encryption", file=sys.stderr)
        return None

    pub_key = serialization.load_pem_public_key(pub_key_pem.encode())
    encrypted = pub_key.encrypt(plaintext.encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def decode_jwt_payload(token):
    """Decode JWT payload without verification."""
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}


# ─── Client ───────────────────────────────────────────────────────────────────

class XunleiClient:
    """Pure-HTTP Xunlei client for fnOS."""

    def __init__(self):
        self.token, nas_ip, fnos_port = get_fnos_token()
        self.base = f"http://{nas_ip}:{fnos_port}"
        self.xunlei = f"{self.base}/cgi/ThirdParty/xunlei/index.cgi"
        self.session = requests.Session()
        self.session.headers["Cookie"] = f"fnos-token={self.token}"
        self.pan_auth = None

        cfg = load_config()
        self.device_id = cfg.get("device_id", "")
        self.folder_id = cfg.get("folder_id", "")
        self.folder_path = cfg.get("folder_path", "")

    def _get_pan_auth(self):
        """Extract pan_auth JWT from the Xunlei page HTML."""
        resp = self.session.get(f"{self.xunlei}/", timeout=10)
        if "invalid token" in resp.text:
            raise RuntimeError("fnos-token expired — re-run to auto-refresh")
        match = re.search(r'uiauth\(value\)\{\s*return\s*"([^"]+)"', resp.text)
        if not match:
            raise RuntimeError(f"Cannot extract pan_auth from HTML ({len(resp.text)} chars)")
        self.pan_auth = match.group(1)
        return self.pan_auth

    def _api(self, path, params=None, body=None, _retry=True):
        """Call a Xunlei API endpoint with auto pan_auth refresh on 403."""
        if not self.pan_auth:
            self._get_pan_auth()
        url = f"{self.xunlei}{path}"
        params = dict(params or {})
        params["pan_auth"] = self.pan_auth
        headers = {"Referer": f"{self.xunlei}/"}
        if body is not None:
            headers["Content-Type"] = "application/json"
            resp = self.session.post(url, params=params, json=body, headers=headers, timeout=15)
        else:
            resp = self.session.get(url, params=params, headers=headers, timeout=15)

        # 403 = pan_auth expired → refresh and retry once
        if resp.status_code == 403 and _retry:
            self.pan_auth = None
            self._get_pan_auth()
            return self._api(path, params, body, _retry=False)
        return resp

    def discover_device(self):
        """Discover device_id and download folder info from API."""
        # device_id from runner task
        resp = self._api("/drive/v1/tasks", params={
            "type": "user#runner",
            "device_space": "",
        })
        tasks = resp.json().get("tasks", [])
        if tasks:
            self.device_id = tasks[0].get("params", {}).get("target", "")

        # folder_id and folder_path from download_paths
        resp2 = self._api("/device/download_paths")
        paths = resp2.json()
        if paths:
            # Pick the first non-system download path (prefer team/vol paths)
            chosen = None
            for p in paths:
                rp = p.get("RealPath", "")
                if rp and not rp.startswith("/var/apps/"):
                    chosen = p
                    break
            if not chosen and paths:
                chosen = paths[0]
            if chosen:
                self.folder_id = chosen.get("Id", "")
                self.folder_path = chosen.get("RealPath", "")

        # Persist
        cfg = load_config()
        cfg["device_id"] = self.device_id
        cfg["folder_id"] = self.folder_id
        cfg["folder_path"] = self.folder_path
        save_config(cfg)

        return {
            "device_id": self.device_id,
            "folder_id": self.folder_id,
            "folder_path": self.folder_path,
        }

    def list_tasks(self, limit=100):
        if not self.device_id:
            self.discover_device()
        params = {
            "space": self.device_id,
            "page_token": "",
            "filters": json.dumps({
                "phase": {"in": "PHASE_TYPE_PENDING,PHASE_TYPE_RUNNING,PHASE_TYPE_PAUSED,PHASE_TYPE_ERROR"},
                "type": {"in": "user#download-url,user#download"},
            }),
            "limit": str(limit),
            "device_space": "",
        }
        resp = self._api("/drive/v1/tasks", params=params)
        if resp.status_code != 200:
            return {"error": resp.text}
        tasks = resp.json().get("tasks", [])
        result = []
        for t in tasks:
            params_inner = t.get("params", {})
            spec = params_inner.get("spec", "")
            phase_match = re.search(r'"phase":"(\w+)"', spec)
            phase = phase_match.group(1).replace("PHASE_TYPE_", "").lower() if phase_match else "unknown"
            result.append({
                "id": t.get("id", ""),
                "name": t.get("name", ""),
                "phase": phase,
                "progress": params_inner.get("progress", "0"),
                "size": params_inner.get("size", "0"),
            })
        return result

    def add_magnet(self, magnet):
        if not self.device_id or not self.folder_id:
            self.discover_device()

        # Step 1: parse magnet
        resp = self._api("/drive/v1/resource/list", body={
            "page_size": 2000,
            "urls": magnet,
        })
        if resp.status_code != 200:
            return {"error": f"resource/list HTTP {resp.status_code}: {resp.text}"}
        data = resp.json()
        resources = data.get("list", {}).get("resources", [])
        if not resources:
            return {"error": "No resources in magnet", "raw": data}
        r = resources[0]
        name = r.get("name", "unknown")
        file_count = str(r.get("file_count", "1"))

        # Step 2: create task
        task_body = {
            "type": "user#download-url",
            "name": name,
            "file_name": name,
            "file_size": "0",
            "space": self.device_id,
            "params": {
                "target": self.device_id,
                "url": magnet,
                "total_file_count": file_count,
                "parent_folder_id": self.folder_id,
                "parent_folder_path": self.folder_path,
                "sub_file_index": "--1,",
                "mime_type": "",
                "file_id": "",
            },
        }
        resp = self._api("/drive/v1/task", body=task_body)
        if resp.status_code != 200:
            return {"error": f"task create HTTP {resp.status_code}: {resp.text}"}
        data = resp.json()
        if data.get("HttpStatus") == 0:
            return {"ok": True, "task": data.get("task", {})}
        return {"error": "task create error", "raw": data}

    def delete_task(self, task_id, delete_files=True):
        if not self.device_id:
            self.discover_device()
        params = {"space": self.device_id, "task_ids": task_id}
        if delete_files:
            params["delete_files"] = "true"
        resp = self._api("/method/delete/drive/v1/tasks", params=params, body={})
        if resp.status_code == 200:
            return {"ok": True}
        return {"error": f"delete HTTP {resp.status_code}: {resp.text}"}

    def auth_info(self):
        if not self.pan_auth:
            self._get_pan_auth()
        payload = decode_jwt_payload(self.pan_auth)
        info = {"pan_auth": self.pan_auth[:40] + "...", "payload": payload}
        if "exp" in payload:
            info["expires"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(payload["exp"]))
            info["remaining_seconds"] = payload["exp"] - int(time.time())
        cfg = load_config()
        info["device_id"] = cfg.get("device_id", "")
        info["folder_id"] = cfg.get("folder_id", "")
        info["folder_path"] = cfg.get("folder_path", "")
        return info


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    client = XunleiClient()

    if cmd == "init":
        info = client.discover_device()
        print(json.dumps(info, indent=2, ensure_ascii=False))

    elif cmd == "list":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 100
        tasks = client.list_tasks(limit=limit)
        if isinstance(tasks, dict) and "error" in tasks:
            print(f"Error: {tasks['error']}", file=sys.stderr)
            sys.exit(1)
        # JSON mode for script integration
        if "--json" in sys.argv:
            print(json.dumps(tasks, ensure_ascii=False))
        else:
            print(f"{'ID':<30} {'Phase':<12} {'Name'}")
            print("-" * 80)
            for t in tasks:
                print(f"{t['id']:<30} {t['phase']:<12} {t['name'][:40]}")
            print(f"\nTotal: {len(tasks)} tasks")

    elif cmd == "add":
        if len(sys.argv) < 3:
            print("Usage: xunlei_http.py add <magnet>", file=sys.stderr)
            sys.exit(1)
        result = client.add_magnet(sys.argv[2])
        if result.get("ok"):
            print(json.dumps(result["task"], ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)

    elif cmd == "delete":
        if len(sys.argv) < 3:
            print("Usage: xunlei_http.py delete <task_id> [--keep-files]", file=sys.stderr)
            sys.exit(1)
        task_id = sys.argv[2]
        keep = "--keep-files" in sys.argv
        result = client.delete_task(task_id, delete_files=not keep)
        if result.get("ok"):
            print(json.dumps({"ok": True, "deleted": task_id}))
        else:
            print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)

    elif cmd == "auth":
        info = client.auth_info()
        print(json.dumps(info, indent=2, ensure_ascii=False))

    elif cmd == "discover":
        # Alias for init
        info = client.discover_device()
        print(json.dumps(info, indent=2, ensure_ascii=False))

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

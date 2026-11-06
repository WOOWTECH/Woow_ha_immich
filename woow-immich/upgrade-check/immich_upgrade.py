"""The upgrade test's data check of Woow Immich (pipeline release-gating/151).

The Store's upgrade test (Woow_HA_App_Store .addon-sync/upgrade_runtime.py)
runs `seed` on the comparison target and `verify` on the new version, on the
same data directories, from the mock Supervisor's container (python3 and
busybox only: no immich CLI, no curl). Both go through Immich's own REST API
at ADDON_URL (the add-on's nginx on port 8080), never its PostgreSQL database:

seed     Immich is up (/api/server/ping), the first admin is created
         (POST /api/auth/admin-sign-up, which only works on a server without
         one) and logs in, an API key is created, a photo with unique pixels is
         uploaded (POST /api/assets) and put in a new album (POST /api/albums),
         and the album lists it.
verify   Immich is up on the new version (it runs its database migrations
         before it answers), the admin still logs in with the same password,
         the API key still authenticates, the album is still there with the
         same name and holds the photo, the photo's original downloads with the
         same bytes and Immich still records the same checksum, and a new
         upload works (then is deleted).

Credentials: seed makes the admin itself, with a random password, and keeps
it and the API key in HOOK_STATE_DIR (seed to verify only; never mounted into
the add-on, never in the report). The add-on has no option for an admin.

Each check goes to $REPORT_DIR/<hook>.json; the hook exits 1 when one fails.
Standard library only (the hooks run on python:3.12-alpine).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib

READY_TIMEOUT = 420
# The whole hook stays inside this, so it always writes its report: the Store
# kills a hook at hook_timeout (600 s; no settings.yaml here) before it can.
HOOK_BUDGET = 480
DEADLINE = time.monotonic() + HOOK_BUDGET
STATE_FILE = "immich-seed.json"
EMAIL = "woow-upgrade@example.com"


def time_left(cap: float) -> float:
    """At most `cap` seconds, and no more than the hook has left; fails the check once the budget is used up."""
    left = DEADLINE - time.monotonic()
    if left < 1:
        raise AssertionError(f"the hook's {HOOK_BUDGET} s budget is used up (hook_timeout is 600 s)")
    return min(cap, left)


def png(width: int = 16, height: int = 16) -> bytes:
    """A small PNG of random pixels: its content (and so its checksum) is unique, so Immich never sees a duplicate."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + secrets.token_bytes(width * 3) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class Client:
    """Immich's REST API, as a bearer access token (after login) or with an API key."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token = ""
        self.api_key = ""
        # No redirects: an answer that redirects is reported as it is.
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None,
                auth: str = "token", timeout: float = 60) -> tuple[int, bytes]:
        h = {"Accept": "application/json", **(headers or {})}
        if auth == "token" and self.token:
            h["Authorization"] = f"Bearer {self.token}"
        elif auth == "key" and self.api_key:
            h["x-api-key"] = self.api_key
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=h)
        timeout = time_left(timeout)
        try:
            with self.opener.open(req, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except (urllib.error.URLError, OSError) as error:
            return 0, str(error).encode()

    def call(self, method: str, path: str, body: object | None = None, want: tuple[int, ...] = (200,),
             auth: str = "token") -> object:
        data = None if body is None else json.dumps(body).encode()
        headers = {} if body is None else {"Content-Type": "application/json"}
        code, raw = self.request(method, path, data, headers, auth)
        if code not in want:
            raise AssertionError(f"{method} {path} -> {code}: {raw[:300].decode(errors='replace')}")
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise AssertionError(f"{method} {path} is not JSON: {raw[:200].decode(errors='replace')}") from error

    def wait_ready(self) -> str:
        """/api/server/ping until it answers pong (the server has migrated its database and listens behind nginx)."""
        deadline = time.monotonic() + time_left(READY_TIMEOUT)
        while True:
            code, raw = self.request("GET", "/api/server/ping", auth="", timeout=10)
            if code == 200 and b"pong" in raw:
                return f"/api/server/ping -> pong (Immich {self.version()})"
            if time.monotonic() > deadline - 3:
                raise AssertionError(f"no pong within the wait: last {code} {raw[:200].decode(errors='replace')}")
            time.sleep(3)

    def version(self) -> str:
        try:
            code, raw = self.request("GET", "/api/server/version", auth="", timeout=10)
        except AssertionError:  # out of time: the version is only report text
            return "unknown"
        try:
            v = json.loads(raw) if code == 200 else {}
            return f"{v['major']}.{v['minor']}.{v['patch']}"
        except (ValueError, KeyError, TypeError):
            return "unknown"

    def login(self, password: str) -> str:
        data = self.call("POST", "/api/auth/login", {"email": EMAIL, "password": password}, want=(200, 201), auth="")
        assert isinstance(data, dict) and data.get("accessToken"), f"login answered without an accessToken: {sorted(data)}"
        assert data.get("isAdmin") is True, "the user that logged in is not an admin"
        self.token = data["accessToken"]
        return f"{EMAIL} logs in (admin, user id {data.get('userId')})"

    def upload(self, name: str, content: bytes) -> str:
        """POST /api/assets as multipart/form-data: the new asset's id."""
        boundary = "woow" + secrets.token_hex(12)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        fields = {"deviceAssetId": f"{name}-{stamp}", "deviceId": "woow-upgrade-check",
                  "fileCreatedAt": stamp, "fileModifiedAt": stamp}
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in fields.items()]
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="assetData"; filename="{name}"\r\n'
                     f"Content-Type: image/png\r\n\r\n".encode() + content + b"\r\n")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        code, raw = self.request("POST", "/api/assets", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        if code not in (200, 201):
            raise AssertionError(f"POST /api/assets -> {code}: {raw[:300].decode(errors='replace')}")
        data = json.loads(raw)
        assert data.get("id") and data.get("status") == "created", f"upload answered {data!r}"[:300]
        return str(data["id"])

    def original(self, asset_id: str) -> bytes:
        code, raw = self.request("GET", f"/api/assets/{asset_id}/original", headers={"Accept": "*/*"})
        if code != 200:
            raise AssertionError(f"GET /api/assets/{asset_id}/original -> {code}: {raw[:200].decode(errors='replace')}")
        return raw

    def album_assets(self, album_id: str) -> tuple[dict, list[str]]:
        """The album and the ids of the assets in it (from the album, or from a search when the album has no list)."""
        album = self.call("GET", f"/api/albums/{album_id}")
        assert isinstance(album, dict), f"album is {album!r}"[:200]
        if isinstance(album.get("assets"), list) and album["assets"]:
            return album, [str(a.get("id")) for a in album["assets"]]
        found = self.call("POST", "/api/search/metadata", {"albumIds": [album_id]})
        items = ((found or {}).get("assets") or {}).get("items") or []
        return album, [str(a.get("id")) for a in items]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003 - urllib's signature
        return None


class Checks:
    """Each check runs even when an earlier one failed, unless it needs what that one made."""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def run(self, name: str, check, needs: bool = True) -> object:
        if not needs:
            self.items.append({"name": name, "result": "skip", "detail": "an earlier check it needs failed"})
            return None
        try:
            value = check()
        except Exception as error:  # noqa: BLE001 - every failure is a failed check with its reason
            self.items.append({"name": name, "result": "fail", "detail": f"{type(error).__name__}: {error}"[:500]})
            print(f"FAIL {name}: {error}", flush=True)
            return None
        detail = value if isinstance(value, str) else "ok"
        self.items.append({"name": name, "result": "pass", "detail": detail})
        print(f"pass {name}: {detail}", flush=True)
        return value if value is not None else True

    def finish(self, hook: str) -> int:
        with open(os.path.join(os.environ["REPORT_DIR"], f"{hook}.json"), "w", encoding="utf-8") as f:
            json.dump({"checks": self.items}, f, indent=1)
        return 1 if any(c["result"] != "pass" for c in self.items) else 0


def state_path() -> str:
    return os.path.join(os.environ["HOOK_STATE_DIR"], STATE_FILE)


def seed() -> int:
    checks, state = Checks(), {}
    im = Client(os.environ["ADDON_URL"])
    up = checks.run("Immich up (/api/server/ping)", im.wait_ready)
    state["version"] = im.version()

    def admin() -> str:
        password = secrets.token_urlsafe(24)
        im.call("POST", "/api/auth/admin-sign-up", {"email": EMAIL, "password": password, "name": "Woow upgrade check"},
                want=(200, 201), auth="")
        state["password"] = password
        return im.login(password)
    logged_in = checks.run("admin created and logs in", admin, bool(up))

    def api_key() -> str:
        made = im.call("POST", "/api/api-keys", {"name": "woow-upgrade-check", "permissions": ["all"]}, want=(200, 201))
        assert isinstance(made, dict) and made.get("secret"), f"API key answered without a secret: {sorted(made)}"
        im.api_key = made["secret"]
        me = im.call("GET", "/api/users/me", auth="key")
        assert isinstance(me, dict) and me.get("email") == EMAIL, f"the API key is {me.get('email')!r}'s"
        state["api_key"] = im.api_key
        return f"API key {(made.get('apiKey') or {}).get('id')} authenticates as {EMAIL}"
    checks.run("API key created", api_key, bool(logged_in))

    name = f"woow-upgrade-{secrets.token_hex(6)}.png"
    content = png()

    def upload() -> str:
        asset_id = im.upload(name, content)
        assert im.original(asset_id) == content, "the original read back differs from what was uploaded"
        info = im.call("GET", f"/api/assets/{asset_id}")
        want = base64.b64encode(hashlib.sha1(content).digest()).decode()
        assert info.get("checksum") == want, f"Immich's checksum {info.get('checksum')!r} is not the file's {want!r}"
        state["asset"] = {"id": asset_id, "name": name, "sha256": hashlib.sha256(content).hexdigest(),
                          "size": len(content), "checksum": want}
        return f"{name} (asset {asset_id}): {len(content)} bytes, reads back the same"
    uploaded = checks.run("photo uploaded", upload, bool(logged_in))

    def album() -> str:
        title = f"Woow upgrade check {secrets.token_hex(4)}"
        made = im.call("POST", "/api/albums", {"albumName": title, "assetIds": [state["asset"]["id"]]}, want=(200, 201))
        assert isinstance(made, dict) and made.get("id"), f"album answered {made!r}"[:300]
        got, ids = im.album_assets(str(made["id"]))
        assert ids == [state["asset"]["id"]], f"album {made['id']} holds {ids}, not the photo"
        state["album"] = {"id": str(made["id"]), "name": title}
        return f"album {title!r} ({made['id']}) holds the photo (assetCount {got.get('assetCount')})"
    checks.run("photo put in an album", album, bool(uploaded))

    with open(state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f)
    return checks.finish("seed")


def verify() -> int:
    checks = Checks()
    im = Client(os.environ["ADDON_URL"])

    def read_state() -> dict[str, object]:
        try:
            with open(state_path(), encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, ValueError) as error:
            raise AssertionError(f"seed state {state_path()} unreadable (did seed run?): {error}") from error
        missing = [k for k in ("password", "api_key", "asset", "album") if not (isinstance(loaded, dict) and loaded.get(k))]
        assert not missing, f"seed state has no {', '.join(missing)}"
        return loaded
    state = checks.run("seed state readable", read_state)
    seeded = state is not None

    def ready() -> str:
        answer = im.wait_ready()
        return f"{answer}; seeded on Immich {state.get('version')}" if seeded else answer
    up = checks.run("Immich up (/api/server/ping; migrations finished)", ready)

    login = checks.run("admin logs in", lambda: im.login(state["password"]), bool(up) and seeded)

    def api_key() -> str:
        im.api_key = state["api_key"]
        me = im.call("GET", "/api/users/me", auth="key")
        assert isinstance(me, dict) and me.get("email") == EMAIL, f"the API key is {me.get('email')!r}'s"
        return f"API key authenticates as {EMAIL}"
    checks.run("API key still authenticates", api_key, bool(up) and seeded)

    def in_album() -> str:
        album, ids = im.album_assets(state["album"]["id"])
        assert album.get("albumName") == state["album"]["name"], \
            f"album {state['album']['id']} is named {album.get('albumName')!r}, {state['album']['name']!r} before"
        assert state["asset"]["id"] in ids, f"album {state['album']['name']!r} holds {ids}, not asset {state['asset']['id']}"
        return f"album {state['album']['name']!r} holds asset {state['asset']['id']}"
    checks.run("photo still in the album", in_album, bool(login))

    def same_photo() -> str:
        got = im.original(state["asset"]["id"])
        assert len(got) == state["asset"]["size"], f"the original has {len(got)} bytes, not the {state['asset']['size']} seeded ones"
        assert hashlib.sha256(got).hexdigest() == state["asset"]["sha256"], "the original has different content (sha256 differs)"
        info = im.call("GET", f"/api/assets/{state['asset']['id']}")
        assert info.get("checksum") == state["asset"]["checksum"], f"Immich's checksum is {info.get('checksum')!r} now"
        assert info.get("originalFileName") == state["asset"]["name"], f"originalFileName is {info.get('originalFileName')!r}"
        return f"{state['asset']['name']}: same {len(got)} bytes and checksum"
    checks.run("photo retrievable, same content", same_photo, bool(login))

    def new_upload() -> str:
        name, content = f"woow-upgrade-new-{secrets.token_hex(6)}.png", png()
        asset_id = im.upload(name, content)
        assert im.original(asset_id) == content, "the new photo read back differs"
        im.call("DELETE", "/api/assets", {"ids": [asset_id], "force": True}, want=(200, 204))
        return f"{name} uploaded, read back and deleted"
    checks.run("new upload works", new_upload, bool(login))
    return checks.finish("verify")


def main(hook: str) -> None:
    sys.exit({"seed": seed, "verify": verify}[hook]())

#!/usr/bin/env python3
"""Terminal Hub — web UI for managing persistent tmux-backed web terminals.

Serves a tabbed, mobile-friendly UI plus a small JSON API. Each tab is a ttyd
iframe attached to a named tmux session (ttyd runs separately with --url-arg,
launching bin/ttyd-tmux-session). Sessions survive disconnects because tmux
owns the shell, not the websocket. Configuration is via HUB_* environment
variables — see the README.
"""

import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Config via environment (see systemd/terminal-hub.service.example):
#   HUB_BIND_HOST   interface to serve the UI on (default localhost only)
#   HUB_BIND_PORT   UI port
#   HUB_TTYD_PORT   port ttyd is serving terminals on
#   HUB_TARGETS     path to the session-targets JSON file
BIND_HOST = os.environ.get("HUB_BIND_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("HUB_BIND_PORT", "8073"))
TTYD_PORT = int(os.environ.get("HUB_TTYD_PORT", "8071"))
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
KEY_RE = re.compile(
    r"^(C-[a-z\[\]\\^_]|Escape|Tab|Up|Down|Left|Right|PageUp|PageDown|Home|End|BSpace|Enter|Space|DC)$"
)


def load_targets():
    """What to run in a new session. "local" (a plain shell) is always present.
    Extra targets come from a JSON file mapping label -> argv list, e.g.
    {"lamachina": ["ssh", "lamachina"]}. Each argv is run directly (no shell)."""
    targets = {"local": None}
    path = Path(os.environ.get("HUB_TARGETS", Path(__file__).with_name("targets.json")))
    try:
        raw = json.loads(path.read_text())
        for label, argv in raw.items():
            if NAME_RE.match(label) and isinstance(argv, list) and all(isinstance(a, str) for a in argv):
                targets[label] = argv
    except (FileNotFoundError, json.JSONDecodeError, ValueError, AttributeError):
        pass
    return targets


SESSION_TARGETS = load_targets()
INDEX = Path(__file__).with_name("index.html")
STATIC = {
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/sw.js": ("sw.js", "text/javascript"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
}


def tmux(*args):
    return subprocess.run(
        ["/usr/bin/tmux", *args], capture_output=True, text=True, timeout=10
    )


def list_sessions():
    fmt = "#{session_name}\t#{session_created}\t#{session_attached}\t#{session_windows}\t#{session_activity}"
    r = tmux("list-sessions", "-F", fmt)
    sessions = []
    if r.returncode == 0:
        for line in r.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) == 5:
                sessions.append({
                    "name": parts[0],
                    "created": int(parts[1]),
                    "attached": int(parts[2]) > 0,
                    "windows": int(parts[3]),
                    "activity": int(parts[4] or 0),
                })
    sessions.sort(key=lambda s: s["created"])
    return sessions


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/" or path == "/index.html":
            body = INDEX.read_bytes().replace(b"__TTYD_PORT__", str(TTYD_PORT).encode())
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/sessions":
            self.send_json({"sessions": list_sessions()})
        elif path == "/api/targets":
            # id + a short hint (e.g. "shell", "ssh"), in config order
            self.send_json({"targets": [
                {"id": k, "hint": "shell" if v is None else v[0]}
                for k, v in SESSION_TARGETS.items()
            ]})
        elif path in STATIC:
            fname, ctype = STATIC[path]
            fpath = Path(__file__).with_name(fname)
            if not fpath.exists():
                return self.send_json({"error": "not found"}, 404)
            body = fpath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/sessions":
            data = self.read_body()
            name = str(data.get("name", "")).strip()
            if not NAME_RE.match(name):
                return self.send_json({"error": "invalid name (A-Za-z0-9_.- only, max 32)"}, 400)
            target = str(data.get("target", "local"))
            if target not in SESSION_TARGETS:
                return self.send_json({"error": "unknown target"}, 400)
            args = ["new-session", "-d", "-s", name, "-c", str(Path.home())]
            cmd = SESSION_TARGETS[target]
            if cmd:
                args += cmd  # run e.g. `ssh lamachina` as the session's process
            r = tmux(*args)
            if r.returncode != 0 and "duplicate session" not in r.stderr:
                return self.send_json({"error": r.stderr.strip()}, 500)
            return self.send_json({"ok": True, "name": name})
        if path == "/api/send":
            data = self.read_body()
            name = str(data.get("name", "")).strip()
            if not NAME_RE.match(name):
                return self.send_json({"error": "invalid session name"}, 400)
            key = data.get("key")
            literal = data.get("literal")
            if key is not None:
                key = str(key)
                if not KEY_RE.match(key):
                    return self.send_json({"error": "key not allowed"}, 400)
                r = tmux("send-keys", "-t", name + ":", "--", key)
            elif literal is not None:
                literal = str(literal)
                if not (0 < len(literal) <= 8) or any(ord(c) < 32 or ord(c) == 127 for c in literal):
                    return self.send_json({"error": "invalid literal"}, 400)
                r = tmux("send-keys", "-l", "-t", name + ":", "--", literal)
            else:
                return self.send_json({"error": "key or literal required"}, 400)
            if r.returncode != 0:
                return self.send_json({"error": r.stderr.strip()}, 500)
            return self.send_json({"ok": True})
        if path == "/api/scroll":
            data = self.read_body()
            name = str(data.get("name", "")).strip()
            if not NAME_RE.match(name):
                return self.send_json({"error": "invalid session name"}, 400)
            direction = str(data.get("dir", ""))
            if direction not in ("up", "down", "exit"):
                return self.send_json({"error": "dir must be up/down/exit"}, 400)
            tgt = name + ":"
            try:
                lines = int(data.get("lines", 3))
            except (TypeError, ValueError):
                lines = 3
            lines = max(1, min(60, lines))
            # One query for everything we need to pick a scroll strategy.
            fmt = "#{pane_in_mode}\t#{mouse_all_flag}#{mouse_button_flag}#{mouse_standard_flag}\t#{mouse_sgr_flag}\t#{pane_width}\t#{pane_height}"
            info = tmux("display", "-p", "-t", tgt, fmt).stdout.strip().split("\t")
            if len(info) != 5:
                return self.send_json({"error": "session not found"}, 404)
            in_mode = info[0] == "1"
            mouse_app = "1" in info[1]   # app is tracking mouse (a full-screen TUI)
            sgr = info[2] == "1"
            try:
                width, height = int(info[3]), int(info[4])
            except ValueError:
                width = height = 24

            if direction == "exit":
                if in_mode:
                    tmux("send-keys", "-X", "-t", tgt, "cancel")
                return self.send_json({"ok": True})

            if mouse_app:
                # Full-screen apps (Claude Code, vim, less…) keep no tmux
                # scrollback — feed them wheel events so they scroll themselves.
                col, row = max(1, width // 2), max(1, height // 2)
                btn = 64 if direction == "up" else 65
                if sgr:
                    seq = "\x1b[<%d;%d;%dM" % (btn, col, row)
                else:
                    seq = "\x1b[M" + chr(btn + 32) + chr(min(col, 223) + 32) + chr(min(row, 223) + 32)
                r = tmux("send-keys", "-l", "-t", tgt, "--", seq * lines)
                if r.returncode != 0:
                    return self.send_json({"error": r.stderr.strip()}, 500)
                return self.send_json({"ok": True})

            # Normal shell: scroll tmux's own scrollback via copy-mode.
            if direction == "down" and not in_mode:
                return self.send_json({"ok": True})  # already at the live bottom
            if not in_mode:
                tmux("copy-mode", "-e", "-t", tgt)  # -e auto-exits at the bottom
            xcmd = "scroll-up" if direction == "up" else "scroll-down"
            r = tmux("send-keys", "-X", "-N", str(lines), "-t", tgt, xcmd)
            if r.returncode != 0:
                return self.send_json({"error": r.stderr.strip()}, 500)
            return self.send_json({"ok": True})
        if path == "/api/rename":
            data = self.read_body()
            old = str(data.get("old", "")).strip()
            new = str(data.get("new", "")).strip()
            if not (NAME_RE.match(old) and NAME_RE.match(new)):
                return self.send_json({"error": "invalid name"}, 400)
            r = tmux("rename-session", "-t", old, new)
            if r.returncode != 0:
                return self.send_json({"error": r.stderr.strip()}, 500)
            return self.send_json({"ok": True})
        self.send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        m = re.match(r"^/api/sessions/([A-Za-z0-9_.-]{1,32})$", self.path.split("?")[0])
        if not m:
            return self.send_json({"error": "not found"}, 404)
        r = tmux("kill-session", "-t", m.group(1))
        if r.returncode != 0:
            return self.send_json({"error": r.stderr.strip()}, 500)
        return self.send_json({"ok": True})


if __name__ == "__main__":
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    print(f"Terminal Hub on http://{BIND_HOST}:{BIND_PORT}")
    server.serve_forever()

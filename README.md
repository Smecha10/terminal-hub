# Terminal Hub

A tabbed, mobile-friendly web UI for managing persistent [tmux](https://github.com/tmux/tmux)-backed terminals, served by a tiny dependency-free Python server in front of [ttyd](https://github.com/tsl0922/ttyd). Open it on your phone over Tailscale/VPN and drive multiple long-running terminals — they survive disconnects because tmux owns the shells, not the browser tab.

Built for a Raspberry Pi, but it runs anywhere Python 3, tmux, and ttyd do.

## Features

- **Tabbed sessions** — one tab per tmux session; create, rename, kill, and drag to reorder. Live/unread dots show activity.
- **Swipe to scroll** — swipe the terminal to scroll back. Full-screen apps (Claude Code, vim, less, htop…) are scrolled via injected mouse-wheel events; plain shells use tmux copy-mode scrollback. Toggle with the `⇅` key.
- **On-screen keys** — `esc`, `tab`, arrows, `ctrl`+chord row, `pgup`/`pgdn`, `home`/`end`, common symbols, and font-size controls — because phone keyboards lack them. Keys are sent server-side via `tmux send-keys` (the ttyd iframe is cross-origin and can't be scripted).
- **New-session targets** — start a tab as a local shell or any configured command, e.g. `ssh my-server` (see [Session targets](#session-targets)).
- **Edge-swipe** between terminals; **installable PWA** (add to home screen).

## Architecture

```
browser ──HTTP──▶ server.py (:8073)   tabs, quick-keys, scroll, session mgmt
   │                    │ subprocess
   │                    ▼
   │                  tmux  ◀── sessions persist here
   └──iframe/WS──▶ ttyd (:8071) ──attaches──▶ tmux session (via bin/ttyd-tmux-session)
```

`server.py` serves the UI and a small JSON API; each tab embeds a ttyd iframe pointed at a named tmux session. Because the iframe is a different origin (a different port), keystrokes and scrolling are routed through the server with `tmux send-keys` rather than scripted in the iframe.

## Requirements

- Python 3.8+ (standard library only — no pip install)
- `tmux`
- `ttyd`

## Install

First install the dependencies (`python3`, `tmux`, and [`ttyd`](https://github.com/tsl0922/ttyd)). On Debian/Raspberry Pi OS `sudo apt install tmux`; ttyd is usually built from source or grabbed from a release.

### Quick install (systemd)

```sh
git clone https://github.com/Smecha10/terminal-hub.git
cd terminal-hub

# bind to a trusted interface — a Tailscale/VPN IP, or omit for localhost only
HUB_BIND_HOST=100.x.y.z ./install.sh
```

`install.sh` renders both systemd units from the templates (filling in your
user, repo path, ttyd binary, host, and ports), seeds `targets.json`, then
enables and starts the services. Run `./install.sh --dry-run` first to preview
the units without touching anything. Then open `http://<host>:8073/` in a
mobile browser and "Add to Home Screen".

### Manual install

```sh
cp targets.example.json targets.json && $EDITOR targets.json   # optional: ssh targets
sudo cp systemd/terminal-hub-ttyd.service.example /etc/systemd/system/terminal-hub-ttyd.service
sudo cp systemd/terminal-hub.service.example      /etc/systemd/system/terminal-hub.service
sudo $EDITOR /etc/systemd/system/terminal-hub-ttyd.service   # set YOUR_USER, paths, --interface
sudo $EDITOR /etc/systemd/system/terminal-hub.service        # set YOUR_USER, paths, HUB_BIND_HOST
sudo systemctl daemon-reload
sudo systemctl enable --now terminal-hub-ttyd.service terminal-hub.service
```

To run it by hand instead of via systemd:

```sh
HUB_BIND_HOST=127.0.0.1 python3 server.py
# and separately:
ttyd --port 8071 --interface 127.0.0.1 --writable --url-arg --ping-interval 20 ./bin/ttyd-tmux-session
```

## Configuration

Set via environment (see the systemd examples):

| Variable         | Default     | Purpose                                    |
| ---------------- | ----------- | ------------------------------------------ |
| `HUB_BIND_HOST`  | `127.0.0.1` | Interface the UI binds to                  |
| `HUB_BIND_PORT`  | `8073`      | UI port                                    |
| `HUB_TTYD_PORT`  | `8071`      | Port ttyd is serving on                    |
| `HUB_TARGETS`    | `targets.json` next to `server.py` | Session-targets file |

### Session targets

`targets.json` maps a picker label to the argv run in a new session (executed directly, no shell). The built-in `local` shell is always offered and needs no entry. Example:

```json
{
  "gpu-box": ["ssh", "gpu-box"],
  "vps": ["ssh", "user@vps.example.com"]
}
```

The "New terminal" sheet shows a target picker whenever more than one target exists.

## Security

**There is no authentication**, and ttyd runs `--writable`. Anyone who can reach the ports gets a root-capable shell as the service user. Only bind to a trusted interface — a Tailscale/VPN address, or `127.0.0.1` behind an authenticating reverse proxy. Do **not** expose it to the public internet or an untrusted LAN.

## License

[Apache-2.0](LICENSE)

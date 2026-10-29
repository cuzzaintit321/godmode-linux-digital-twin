# ◈ GODMODE — Linux Digital Twin & Infrastructure Intelligence

A runnable distributed **Linux observability prototype**. A Python read-only agent runs on each Fedora/Ubuntu host and sends CPU, memory, disk, process, systemd, Docker, network and disk data to a central FastAPI control plane with SQLite persistence. The dark responsive browser dashboard provides fleet health, process inspection, a host/container relationship map, historical CPU trend, event history, snapshots, and basic rule-based diagnostics.

## Start central server on yeet or your workstation

```bash
cd godmode
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GODMODE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
printf 'Save token somewhere safe: %s\n' "$GODMODE_TOKEN"
uvicorn server.main:app --host 127.0.0.1 --port 8383
```

Open http://127.0.0.1:8383, click **Token**, and enter your saved token. For remote browser access, use `ssh -L 8383:127.0.0.1:8383 yeet` on the workstation. Native local loopback mode can run without `GODMODE_TOKEN` for quick local trials, but **always configure a token for LAN connectivity**.

## Run agent locally

Use a second terminal in the same project environment:

```bash
export GODMODE_TOKEN='PASTE_YOUR_TOKEN'
python -m agent.main --server http://127.0.0.1:8383 --once
python -m agent.main --server http://127.0.0.1:8383
```

## Add Fedora machines over your LAN (only on trusted network)

On the Ubuntu control-plane host, listen on `--host 0.0.0.0` **only if protected with GODMODE_TOKEN and a host firewall restricted to your LAN**. On each Fedora host copy the project or just `agent/` and `requirements.txt`, set up a Python virtual environment, use the *same token*, and run:

```bash
export GODMODE_TOKEN='PASTE_YOUR_TOKEN'
python -m agent.main --server http://192.168.1.130:8383
```

**Security warning:** HTTP with a static token is **not encrypted**. For reliable secure remote communication use WireGuard/Tailscale, SSH tunnels, or an HTTPS reverse proxy with authenticated access. Never expose this application or agent ingest API directly to the public internet. The dashboard is single-operator and the API token grants access to ingest and all reads. No RBAC, TLS server, users, agents' individual credentials, signed payloads, or hardened production deployment exist yet. Unauthenticated loopback mode is for isolated local use only; do not enable `GODMODE_ALLOW_UNAUTH_LAN` unless you understand the risks.

## Deployment / architecture

```
Fedora xps-8940 agent ─┐
Fedora xps-8930 agent ─┼──► GODMODE Control Plane :8383 ── SQLite + Web UI
Ubuntu yeet agent ────┘
```

Each agent sends current samples about every five seconds. Reports older than 45 seconds become offline. Agents gather processes through psutil, service inventory through systemctl, Docker through docker CLI (if permitted), and read-only listening sockets through psutil (subject to OS permissions). No remote commands are exposed. Container relationship graph shows reported host/container association, **not a true auto-discovered network or a 3D twin**.

Endpoints: `GET /health`, `POST /api/report`, `GET /api/overview`, `GET /api/history/{host_id}`, `GET /api/diagnostics/{host_id}`, `POST /api/snapshots/{host_id}`, `GET /api/snapshots/{host_id}`, `/docs`.

The SQLite database defaults to `data/godmode.sqlite` and is excluded from Git. Last 1440 samples per host are retained (approximately two hours at five-second intervals). `hours=24` is a query window, but retention limits results. Snapshots preserve metadata, **not files or backups**. The agent runs as your user and won't see processes/systemd/Docker info your user can't access. You should not add your user to Docker's group merely to make metrics work: Docker group grants broad root-equivalent permissions.

## Tests

```bash
pip install -r requirements.txt
pytest -q
```

## Product roadmap, not yet implemented

AI-assisted diagnosis, true network dependency discovery, 3D visualization, config diffs, fleet policies, isolated fault simulation, self-healing and approved playbooks. The delivered version is **read-only except for writing its local telemetry/events/snapshots**.

## License

MIT

# VideoSnap

VideoSnap is a FastAPI-based video download web app for YouTube, Instagram, X/Twitter, TikTok, and Facebook.

The current production deployment runs on a small Google Cloud VM and is exposed through Cloudflare Tunnel:

- Production domain: `https://download.lsh.indevs.in`
- Backend service: `videosnap.service`
- Backend listen address: `127.0.0.1:8002`
- Cloudflare Tunnel route: `download.lsh.indevs.in -> http://127.0.0.1:8002`

## Features

- Single input box for supported video URLs.
- Direct download and server-side merged download support.
- Access code required only when the user clicks download.
- Daily download quota: 5 downloads per IP per day.
- Maximum output file size: 300 MB.
- Server-side merge concurrency limit: 1 merge at a time.
- Merge timeout: 180 seconds.
- Temporary merge files are removed after download.
- Instagram and YouTube can use a local Cloudflare WARP SOCKS proxy when available.
- Access logs and noisy thumbnail debug logs are disabled in production.

## Local Development

Install dependencies:

```bash
uv sync
cd ig_node_module
npm install
cd ..
```

Run locally:

```bash
uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Open:

```text
http://127.0.0.1:8000
```

## Environment Variables

The production service uses these defaults:

```text
ACCESS_CODE=hua
DAILY_DOWNLOAD_LIMIT=5
MAX_DOWNLOAD_BYTES=314572800
MERGE_CONCURRENCY=1
MERGE_TIMEOUT_SECONDS=180
```

Optional logging setting:

```text
LOG_LEVEL=WARNING
```

## Production Service

The recommended production service file is:

```text
deploy/videosnap-user.service
```

It runs the app as a user-level systemd service with resource limits:

- `MemoryMax=700M`
- `CPUQuota=80%`
- `TasksMax=80`
- `NoNewPrivileges=true`

Install or update the service on the server:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/videosnap-user.service ~/.config/systemd/user/videosnap.service
systemctl --user daemon-reload
systemctl --user enable --now videosnap.service
```

If the service should continue after logout:

```bash
sudo loginctl enable-linger "$USER"
```

## Cloudflare Tunnel

The server-side Cloudflare Tunnel config should include:

```yaml
- hostname: download.lsh.indevs.in
  service: http://127.0.0.1:8002
```

The DNS record in Cloudflare should be a proxied CNAME to the tunnel target.

## WARP Proxy

For better Instagram and YouTube reliability on cloud IPs, the server can run Cloudflare WARP in local proxy mode:

```text
127.0.0.1:40000
```

The app checks this port before adding proxy settings for YouTube merge downloads. Instagram extraction also supports this SOCKS proxy from the Node extraction module.

## Server Notes

Current Google Cloud VM setup:

- Machine type: `e2-micro`
- Disk: 30 GB standard persistent disk
- Swap: 4 GB `/swapfile`
- App directory: `/home/li923745997/videosnap`
- Node path: `/home/li923745997/.local/node/bin`
- Python dependencies managed by `uv`

## Safety Controls

The app includes basic abuse controls:

- Access code required for actual downloads.
- Per-IP daily download limit.
- 300 MB maximum file size.
- Merge concurrency and timeout limits.
- systemd memory, CPU, and task limits.

These controls are intentionally conservative because the production VM is small.

## Disclaimer

This project is for personal learning and testing. Use it only with content and platforms where you have the right to download media.

# Deployment

Dishpute ships as an OCI container with PostgreSQL. The production Compose file is
intended for a private server behind an HTTPS reverse proxy such as Caddy, nginx, or
Traefik.

## Requirements

- A Linux host with Docker Compose
- A DNS name pointing at the host
- HTTPS termination at the reverse proxy
- A randomly generated PostgreSQL password

## Start the service

```bash
export POSTGRES_PASSWORD="$(openssl rand -base64 32)"
docker compose -f compose.production.yaml up -d --build
```

The web service listens only on `127.0.0.1:8000`. Configure the reverse proxy to send
the public HTTPS origin to that address. The container applies Alembic migrations
before Uvicorn starts and exposes `/health` for monitoring.

For a private Tailscale-only deployment, set `BIND_ADDRESS` to the server's Tailscale
IPv4 address. Do not set it to `0.0.0.0` unless a host firewall restricts access.

To make the same deployment available through Tailscale Serve HTTPS, include the
Tailscale Compose override. It adds a loopback listener without removing the existing
private-address listener used by nginx:

```bash
docker compose \
  -f compose.production.yaml \
  -f compose.tailscale.yaml \
  up -d --build
tailscale serve --bg 8000
```

Tailscale Serve provisions and renews HTTPS for the machine's private `*.ts.net`
hostname. It does not issue a certificate for a custom hostname.

The production configuration disables `X-Actor-User-Id`. Browser access therefore
requires a real bearer session created through Dishpute signup or login.

## Before public MCP access

Do not expose the current local MCP process publicly. Its environment configuration
selects one fixed member and exists only for local client development. Public MCP
requires an OAuth authorization flow so each Codex, Claude, or ChatGPT connection is
bound to the correct Dishpute member and household. That service also needs the final
public HTTPS origin for redirect and metadata URLs.

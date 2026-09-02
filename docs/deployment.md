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

## Public OAuth-protected MCP gateway

The production Compose file includes a separate MCP service. The Tailscale override
publishes that service on loopback only, at `127.0.0.1:8001`. Set its public issuer
URL before starting the stack:

```bash
export DISHPUTE_MCP_PUBLIC_URL="https://YOUR-NODE.YOUR-TAILNET.ts.net:8443"
docker compose \
  -f compose.production.yaml \
  -f compose.tailscale.yaml \
  up -d --build
```

Publish only the MCP gateway through Tailscale Funnel. Port 443 remains a private
Tailscale Serve route for the web application:

```bash
tailscale serve --bg 8000
tailscale funnel --bg --https=8443 8001
```

The MCP connector URL is:

```text
https://YOUR-NODE.YOUR-TAILNET.ts.net:8443/mcp
```

The gateway supports OAuth Authorization Code with PKCE, dynamic client
registration, refresh-token rotation, revocation, and the standard MCP protected
resource metadata endpoint. Authorization uses the member's existing Dishpute email
and password and binds tokens to that member's active Household. Accounts with zero
or multiple active Households cannot authorize until explicit Household selection is
implemented.

Verify the isolation and authentication boundary:

```bash
tailscale serve status
tailscale funnel status
curl https://YOUR-NODE.YOUR-TAILNET.ts.net:8443/.well-known/oauth-authorization-server
curl -i -X POST https://YOUR-NODE.YOUR-TAILNET.ts.net:8443/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

The final request must return `401` with a `WWW-Authenticate` header pointing to the
protected resource metadata. Disable public MCP access without affecting the private
web application:

```bash
tailscale funnel --https=8443 off
```

The production configuration disables `X-Actor-User-Id`. Browser access therefore
requires a real bearer session created through Dishpute signup or login.

## MCP security boundary

Never expose the fixed-member local MCP mode publicly. Public deployments must set
`DISHPUTE_MCP_PUBLIC_URL`, which enables the OAuth flow so each Codex, Claude, or
ChatGPT connection is bound to the correct Dishpute member and Household.

# Phase 2C catalog gallery on the Mac

> Historical 2C procedure. For the current HTTPS and login flow, use
> [phase-2d.md](phase-2d.md). The HTTP commands below no longer work.

Phase 2C adds read-only catalog endpoints and a browser gallery to the
existing FastAPI server. It uses the existing 0004_derivatives schema and the
14 imported assets. It needs no SQLite migration, manifest import, or
derivative regeneration.

## Update the existing checkout

Run on the Mac after the branch is published. First inspect local changes in
the checkout; preserve the existing .env, database, derivative cache, and any
local modifications. Resolve a dirty checkout before switching branches.

    cd /Volumes/SSDMacbook/desenvolvimento/drone-media-manager
    git status --short
    git fetch origin
    git switch codex/phase-2c-gallery
    git pull --ff-only origin codex/phase-2c-gallery
    uv sync
    launchctl kickstart -k "gui/$(id -u)/com.drone-media-manager.server"
    curl -fsS http://127.0.0.1:8000/health

The restart loads the new API and pages in the already configured LaunchAgent.
Do not change its host, port, TLS, or Tailscale configuration for this phase.

## Check the real catalog

    curl -fsS http://127.0.0.1:8000/api/catalog/trips
    curl -fsS http://127.0.0.1:8000/api/catalog/trips/teste-fase-1/assets
    curl -fsS 'http://127.0.0.1:8000/api/catalog/trips/teste-fase-1/assets?classification=INSTAGRAM_9X16'

Expect one trip, 14 assets, and two filtered portrait videos. Open /gallery
in a browser, enter the trip, filter INSTAGRAM_9X16, and open both cards. The
video player should show each proxy in portrait orientation; seek to a later
point in each. Return to the gallery and check /health again. The proxy URL
accepts single HTTP byte ranges and returns 206 with Content-Range; missing
or invalid derivatives return 404 or 416.

The API accepts only asset_id for media lookup. It never serves an original
from the OMV and only serves registered local derivatives with READY status.
Thumbnails use a private one-hour browser cache with an ETag.

## Grupos confirmados

A galeria e o catálogo mostram o grupo confirmado separadamente do POI inicial.
Use o filtro **Grupo confirmado** para ver um grupo ou **Sem grupo**; assets sem
GPS continuam visíveis. O ID de grupo pertence sempre à viagem exibida.

## Phase 2D successor

The 2C procedure above records the earlier read-only acceptance. Phase 2D adds HTTPS-only login, persistent selection and separate ORIGINAL downloads. Use [the Phase 2D Mac runbook](phase-2d.md) for the migration, verified SQLite backup, TLS setup, initial user and Chrome acceptance. The 2C HTTP catalog commands above are historical and return 426 after the 2D application is loaded.

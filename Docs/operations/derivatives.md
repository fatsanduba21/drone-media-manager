# Phase 2B derivatives on the Mac

Use the already imported catalog and mounted OMV share. Originals are read through
`DMM_OMV_ROOT` and the catalog's safe relative paths. The cache is local to the
Mac; set `DMM_DERIVATIVES_ROOT` to a directory outside the OMV and synced roots.
If unset, the cache is a `derivatives` directory beside the SQLite database.

On the current checkout, back up the existing database before migrating:

```bash
cd /Volumes/SSDMacbook/desenvolvimento/drone-media-manager
db=$(uv run python -c 'from drone_media_manager.config import get_server_settings; print(get_server_settings().database_path)')
sqlite3 "$db" ".backup '$db.pre-2b-$(date +%Y%m%d-%H%M%S).bak'"
uv sync
uv run dmm-server migrate
uv run dmm-derivatives generate --trip teste-fase-1
uv run dmm-derivatives generate --trip teste-fase-1
```

The first run should report 19 generated: 14 JPEG thumbnails and 5 MP4
proxies. The second should report 19 reused. A nonzero `failed` count gives
exit code 2 and lists each `asset_id`, kind, and error. Check the catalog with:

```bash
sqlite3 "$db" "SELECT kind,status,COUNT(*) FROM derivatives GROUP BY kind,status;"
```

`derivatives.catalog_asset_id` joins to `catalog_assets.id` to locate a
derivative by `asset_id`. Only rows with `status='READY'` are usable. Their
`rel_path` is relative to `DMM_DERIVATIVES_ROOT`. `source_sha256`,
`profile_version`, and `output_sha256` control reuse; a changed source or
profile, or corrupt output, regenerates the file. The generator writes a
temporary sibling and atomically replaces the final file, then commits the
new metadata. `ERROR` rows retain the last error for diagnosis.

The new database revision is `0004_derivatives`. Restart the existing
LaunchAgent after migration because the server checks that its database is at
the current revision, then check health:

```bash
launchctl kickstart -k "gui/$(id -u)/com.drone-media-manager.server"
curl -fsS https://NOME_DNS_DO_CERTIFICADO:8000/health
```

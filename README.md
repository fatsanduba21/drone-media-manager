# Drone Media Manager

Fluxo de produção: no Windows, `dmm-organize` lê o cartão/pasta sem alterar a
origem, copia e verifica os originais no OMV e publica `MANIFESTO.json`. No Mac,
`dmm-catalog` importa o manifesto para SQLite local; derivados, galeria,
seleção, download e editorial 3A/3B consomem esse catálogo.

Comece por [Docs/README.md](Docs/README.md), que identifica os contratos e
runbooks atuais. O fluxo distribuído `dmm-worker`/jobs/snapshots é
**LEGACY/EXPERIMENTAL** e não faz parte da operação de produção.

## Operação

- Windows: [organizar mídia](Docs/operations/windows-organize.md)
- Mac: [servidor e importação](Docs/operations/mac-server.md)
- Galeria, seleção e downloads: [fase 2D](Docs/operations/phase-2d.md)
- Editorial: [agrupamento](Docs/operations/grouping.md) e [nomes](Docs/operations/location-names.md)

Para acesso pela LAN com login, use HTTPS com certificado válido para o nome
DNS acessado pelo navegador. Mantenha SQLite e derivados em disco local, fora
do OMV e de pastas sincronizadas.

## Development

```text
uv sync --all-groups
uv run pytest tests/unit tests/integration tests/security -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

The database is local to the Mac. Do not place the active SQLite file on OMV,
SMB, iCloud, or another synchronized directory.

# Checkpoint da Fase 2B — thumbnails e proxies

**Data:** 22/09/2026  
**Branch:** `codex/phase-2b-derivatives`  
**Base:** `b0a90cd` (`codex/phase-2a-mac-integration`)

## Implementação

- `dmm-derivatives generate --trip teste-fase-1` lê os `ORIGINAL` do catálogo por paths relativos validados contra `DMM_OMV_ROOT`. Não grava no OMV.
- `DMM_DERIVATIVES_ROOT` aponta para cache local; quando omitido, usa `derivatives` ao lado do SQLite. A configuração impede que o cache fique no OMV ou numa raiz sincronizada.
- Thumbnail de vídeo: JPEG até 480 px. Thumbnail de foto: JPEG até 480 px com orientação EXIF aplicada por Pillow.
- Proxy: MP4 H.264, `yuv420p`, lado maior até 720 px, `+faststart`, AAC somente se a origem tiver áudio. FFmpeg aplica rotação antes do redimensionamento.
- A tabela `derivatives` (`0004_derivatives`) registra `catalog_asset_id`, tipo, estado, versão do perfil, SHA-256 da origem e da saída, caminho relativo e erro. A Fase 2C pode consultar por `catalog_assets.asset_id` e usar somente linhas `READY`.
- Hash ou perfil diferente, arquivo ausente/corrompido ou mídia inválida provocam regeneração. A saída é escrita em um temporário irmão e promovida com `os.replace` antes da atualização do registro.

## Verificações no desenvolvimento

`pytest -q`: **223 passed, 1 skipped**. `ruff check .`, `mypy src` e `ruff format --check` dos arquivos alterados passaram. Os testes novos cobrem reutilização, mudança do hash da origem e do perfil, corrupção do cache, falha de geração com remoção do temporário e orientação EXIF de foto.

## Aceite no Mac real

O checkout `/Volumes/SSDMacbook/desenvolvimento/drone-media-manager` foi atualizado pelo GitHub para `235fce1`. As alterações locais prévias (`.env.example` removido e arquivos `.DS_Store`) foram preservadas no stash `mac-pre-2b-local`; o `.env` operacional permaneceu no lugar. Antes da migration, foi criado e confirmado o backup SQLite `dmm.sqlite3.pre-2b-20260922-225714.bak`. A revisão do banco após migration é `0004_derivatives`.

Com o catálogo da 2A, sem reimportação:

| Verificação | Resultado |
| --- | ---: |
| Primeira geração | 19 gerados, 0 reutilizados, 0 falhas |
| Segunda geração | 0 gerados, 19 reutilizados, 0 falhas |
| Registros prontos | 14 `THUMBNAIL`, 5 `PROXY` |
| Preview read-only com `--verify-hash` | 14 assets e 18 arquivos `AVAILABLE`, 0 conflitos, 0 ausentes |

`ffprobe` confirmou os cinco proxies em H.264 e `yuv420p`: dois verticais `406×720` (`INSTAGRAM_9X16`) e três horizontais `720×406` (`YOUTUBE_16X9`). Nenhum desses originais tinha áudio; os proxies ficaram sem faixa de áudio. Nos cinco MP4, o átomo `moov` aparece antes de `mdat` (`faststart=True`).

Os cinco proxies foram abertos e reproduzidos no navegador via servidor HTTP temporário limitado a links dos proxies no cache do Mac, acessado por Tailscale. Os dois verticais apareceram em retrato; os horizontais apareceram em paisagem. O servidor de prévia foi encerrado e a pasta temporária removida.

O LaunchAgent `com.drone-media-manager.server` foi reiniciado após a migration. Uma chamada local feita imediatamente após o `kickstart` ocorreu antes da escuta e falhou; a checagem seguinte de `/health` via Tailscale retornou `healthy` para banco, OMV, `ffmpeg`, `ffprobe` e worker.

Esta fase não adiciona API de catálogo, galeria, seleção ou downloads.

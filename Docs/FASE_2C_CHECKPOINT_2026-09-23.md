# Checkpoint da Fase 2C — API de catálogo e primeira galeria

**Data:** 23/09/2026  
**Branch:** codex/phase-2c-gallery  
**Base:** origin/main em 1c8e475ae16cbb0c1fbb6dbcdf5b9668327143af

## Implementação publicada

- API read-only: viagens, detalhe da viagem, assets da viagem, detalhe do asset,
  thumbnail e proxy, sempre por asset_id para mídia.
- Filtros combináveis por classification, poi, movement, people e media_type.
  POI, movimento e pessoas usam comparação Unicode e o mesmo fallback entre
  POI final e sugerido usado na apresentação.
- Serving somente de derivados READY com perfil atual, caminho registrado
  canônico dentro do cache local, arquivo presente e tamanho esperado.
  Originais do OMV não são servidos. Proxy usa o FileResponse do Starlette para
  HTTP Range e seek; Range inválido ou múltiplo recebe 416. Thumbnail usa cache
  privado de uma hora e ETag.
- UI servida pelo FastAPI: lista de viagens, galeria com filtros e cards, e
  detalhe com player. O layout do player mantém vídeos verticais em retrato.
  Não há seleção, download, autenticação final nem alteração de bind/rede.
- Sem migration SQLite. Nenhum import do manifesto ou geração de derivados
  foi executado nesta fase.

## Verificação local

- pytest: 246 passed, 2 skipped.
- Ruff check: passou.
- Ruff format --check dos quatro arquivos Python alterados: passou.
- mypy src: passou.
- Os testes novos cobrem filtros, paths, estado READY, cache, Range e
  navegação. O teste novo de escape por symlink foi pulado neste Windows
  porque a criação de symlink não está disponível. A suíte também já tinha
  um teste pulado antes da Fase 2C.

## Aceite no Mac

Antes da atualização, /health via Tailscale retornou healthy para banco, OMV,
ffmpeg, ffprobe e worker. O host respondeu na rede, mas a autenticação SSH
sem senha foi recusada e não havia terminal Mac anexado a esta tarefa.
Portanto, o checkout do Mac não foi atualizado, o LaunchAgent não foi
reiniciado e a galeria não foi testada com os 14 assets reais nesta execução.
Ficam pendentes a abertura da viagem, o filtro dos dois vídeos 9:16, seek nos
dois proxies, retorno à galeria e uma nova verificação de /health após a
atualização. O procedimento está em operations/gallery.md.

O checkout principal Windows permanece em main com os documentos não
rastreados originais preservados. Não houve merge na main.

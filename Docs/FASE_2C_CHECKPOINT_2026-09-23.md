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

O checkout estava limpo em 1c8e475 na branch da Fase 2B. O Mac buscou a
branch 2C publicada, mudou para ela e executou `uv sync`. O LaunchAgent
`com.drone-media-manager.server` foi reiniciado para carregar as novas rotas.
O `curl` imediato após o reinício encontrou a porta 8000 ainda fechada;
uma nova chamada após a inicialização retornou `healthy` para banco, OMV,
ffmpeg, ffprobe e worker. Não houve migration SQLite, reimportação do
manifesto nem regeneração de derivados.

- A API real retornou uma viagem (`teste-fase-1`) com 14 assets e dois vídeos
  ao filtrar `classification=INSTAGRAM_9X16`.
- No navegador, a viagem abriu com 14 cards e 14 thumbnails carregados. O
  filtro mostrou os dois vídeos verticais. Cada detalhe abriu o proxy em
  406×720, com `object-fit: contain`; o seek chegou a 10 s no primeiro e 14 s
  no segundo, sem erro de mídia.
- Ambos os proxies responderam `206 Partial Content` ao solicitar
  `Range: bytes=1024-2047`, com `Content-Range` e 1024 bytes. O retorno à
  galeria mostrou novamente os 14 cards, e `/health` final via Tailscale
  permaneceu `healthy` em todos os componentes.

O aceite foi executado pelo navegador e pela API acessados via Tailscale a
partir do Windows, com o serviço e os assets reais hospedados no Mac. A
saída do terminal SSH anexado confirmou o fetch, a troca de branch, o
`uv sync`, o reinício do LaunchAgent e o HEAD 2c4331b com checkout limpo.
A verificação local de `/health` no próprio Mac também retornou `healthy`.

O checkout principal Windows permanece em main com os documentos não
rastreados originais preservados. Não houve merge na main.

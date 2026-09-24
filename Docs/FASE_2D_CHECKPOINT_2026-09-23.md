# Checkpoint da Fase 2D — seleção persistente e originais separados

**Data:** 23/09/2026
**Branch:** codex/phase-2d-selection-download
**Base:** origin/main em 3aaeafc12e57a646dc3bb50c24d9dd8ce57a70f9

## Decisão de produto

A usuária usa Chrome como navegador padrão no MacBook e pode usar Safari. O botão Baixar selecionados solicita um download por ORIGINAL selecionado; não cria ZIP, não exige descompactação e não duplica o espaço local com um arquivo compactado. O painel informa quantidade e tamanho total, explica a possível permissão de downloads múltiplos do Chrome e conserva links individuais para recuperação. O Safari dispõe dos links individuais.

## Implementação local

- Migration 0005_gallery_auth: User, UserSession e AssetSelection com constraints e unicidade por usuário/asset.
- Hash Argon2id, comando local dmm-server user create --username, senha oculta, sessão revogável de 12 horas, cookies Secure/HttpOnly/SameSite=Lax, CSRF e limitação de tentativas.
- Login, galeria, catálogo, thumbnails, proxies e downloads exigem HTTPS e sessão no servidor. Rotas de worker e /health preservadas.
- Seleção idempotente em SQLite, isolada por usuário e persistente entre sessões; estado e contagem na galeria.
- Download individual usa somente AssetFile ORIGINAL registrado e AVAILABLE sob DMM_OMV_ROOT, com checagens de path, arquivo e tamanho. Nome editorial sanitizado em Content-Disposition. Preflight de selecionados retorna URLs e tamanhos; lote sem ZIP.
- Filtros, derivados e HTTP Range existentes continuam cobertos pela suíte.

## Verificação no worktree Windows

- pytest geral: 272 passed, 3 skipped, 143 warnings. Os 3 skips incluem testes dependentes de symlink indisponível neste Windows.
- Ruff check: passou.
- mypy src: passou, sem problemas em 82 arquivos.
- Ruff format --check dos nove arquivos alterados: passou.
- Nenhum manifesto foi reimportado; nenhum derivado foi regenerado. Checkout principal e documentos não rastreados foram preservados.

## Estado remoto do Mac e aceite

O usuário aplicou o procedimento no Mac mini: backup SQLite, HTTPS nativo na porta 8000, migration 0005 e criação local do usuário editor. O servidor iniciou com HTTPS no nome Tailscale mac-mini-de-sergio-3.tail689ec7.ts.net; a consulta remota a /health respondeu 200 e mostrou os componentes saudáveis. O login autenticado respondeu 303. A galeria apresentou os 14 assets da viagem de teste e permitiu solicitar downloads individuais dos originais.

Inicialmente os downloads ficavam em 0 bytes. O servidor registrava GET de /download com 200, e um pedido HTTP Range de 1 KB devolvia 206 e Content-Length 1024, mas a leitura do corpo expirava inclusive em um cliente httpx executado no próprio Mac mini. A leitura direta de 1 MB do mesmo arquivo OMV no Terminal levou 0,109 s. O log do macOS atribuiu a solicitação de acesso ao disco ao processo uv responsável pelo serviço. Ao abrir o Mac, o usuário encontrou a autorização de acesso ao disco pendente para uv, concedeu-a e os downloads passaram a funcionar. Esse diagnóstico aponta para a permissão do macOS, não para uma falha do Tailscale ou dos navegadores.

O usuário comparou os SHA-256 dos arquivos baixados com os SHA-256 dos AssetFile ORIGINAL correspondentes e confirmou que todos coincidiram. Esta confirmação conclui o teste de integridade dos downloads feitos; os valores dos hashes e o número exato de arquivos não foram transcritos neste checkpoint.

**Ainda para a Fase 2E:** executar o fluxo completo no MacBook da usuária, na LAN, com o Windows desligado; confirmar persistência após fechar e reabrir o navegador; filtro INSTAGRAM_9X16; proxy com seek; três originais separados, nomes editoriais e SHA-256 nesse cenário; download individual; proteção sem sessão e /health final. Não declarar aceite end-to-end antes dessas evidências. O procedimento operacional está em Docs/operations/phase-2d.md.

## Riscos operacionais

O certificado Tailscale salvo como arquivo exige renovação e reinício do serviço para carregar arquivos renovados. Ao ativar TLS na porta atual, o worker Windows com DMM_SERVER_URL em http:// precisa mudar para https:// com o nome do certificado; suas rotas e tokens permanecem os mesmos. Um arquivo do OMV pode desaparecer após o preflight; cada GET individual revalida e o painel oferece repetição por link individual. A permissão para downloads múltiplos depende do Chrome no MacBook, ainda não validado no ambiente real.

A implementação 2D está concluída. A Fase 2E ainda não foi executada. Não houve merge ou push para main.

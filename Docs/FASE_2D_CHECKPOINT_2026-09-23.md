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

A consulta ao Tailscale do Windows mostrou o Mac online no DNS mac-mini-de-sergio-3.tail689ec7.ts.net. Em 23/09/2026, a tentativa de HTTPS confiável na porta 8000 falhou na negociação TLS, enquanto o endpoint HTTP existente respondeu na mesma porta. Um SSH novo em modo não interativo foi negado por autenticação; a sessão atual não permite executar comandos administrativos no Mac sem interação local. Por isso, nenhum backup operacional, migration, criação de usuário, alteração de TLS, reinício ou download real foi executado nesta fase. Não houve login com credenciais em HTTP.

**Pendências de aceite no Mac:** backup SQLite verificado antes da migration; configuração e verificação de HTTPS confiável; atualização do checkout pela branch publicada; migration 0005; criação local do usuário; teste de login e proteção sem sessão; seleção de três assets reais e persistência após fechar/reabrir; três arquivos separados no Chrome e permissão de downloads múltiplos; SHA-256 contra AssetFile ORIGINAL; download individual; /health final. O procedimento completo está em Docs/operations/phase-2d.md.

## Riscos operacionais

O certificado Tailscale salvo como arquivo exige renovação e reinício do serviço para carregar arquivos renovados. Ao ativar TLS na porta atual, o worker Windows com DMM_SERVER_URL em http:// precisa mudar para https:// com o nome do certificado; suas rotas e tokens permanecem os mesmos. Um arquivo do OMV pode desaparecer após o preflight; cada GET individual revalida e o painel oferece repetição por link individual. A permissão para downloads múltiplos depende do Chrome no MacBook, ainda não validado no ambiente real.

A Fase 2E não foi iniciada. Não houve merge ou push para main.

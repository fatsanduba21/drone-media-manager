# Nomes, galeria e seleção após o saneamento — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar nomes físicos neutros às novas cópias no OMV, mostrar os grupos confirmados na galeria, selecionar sem recarregar a página e produzir nomes editoriais somente nas cópias baixadas.

**Architecture:** O Windows continua responsável por copiar/verificar originais e publicar o manifesto. O Mac continua dono dos grupos, da seleção por usuário e dos nomes editoriais; nenhum grupo descoberto depois da importação renomeia arquivos do OMV. Cada tarefa abaixo produz uma entrega independente, revisável e testável.

**Tech Stack:** Python 3.12/3.13, uv, FastAPI, SQLAlchemy, SQLite, HTML/JavaScript nativo, pytest.

**Spec:** `Docs/FASE_3B_CHECKPOINT_2026-09-24.md`, seção “Regressão real com noronha-teste”; contrato atual em `Docs/architecture/STORAGE_CONTRACTS.md`.

## Estado de partida e limites

- Base: branch `chore/pre-phase-3c-codebase-consolidation`, commit `67de548`. A ordenação temporal e o filtro editorial já passaram no Mac após backup e migração.
- O aceite integral da 3B ainda depende da matriz real do checkpoint. Estas melhorias não declaram a 3B aceita nem iniciam a 3C.
- Os 18 originais já publicados em `noronha-teste`, seus SRT, hashes e caminhos no manifesto não podem ser renomeados ou movidos por esta execução.
- Manter `asset_id` estável, pareamento MP4/SRT, validação independente de hash, autenticação HTTPS, CSRF e seleção isolada por usuário.
- Nenhum ZIP, serviço de nuvem, dependência JavaScript nova ou migração SQLite especulativa.
- Para “selecionar tudo”, o escopo é **somente os assets exibidos pelos filtros atuais**. A ação “desmarcar exibidos” também preserva seleções ocultas.

## Review Focus

- Repetir PLAN/APPLY numa viagem com manifesto antigo não propõe novos caminhos nem duplica originais (Tarefa 4).
- Nome de grupo com acentos, caracteres proibidos ou colisões produz download seguro e único, sem alterar o arquivo no OMV (Tarefa 5).
- Seleção em massa com ID de outra viagem falha inteira; nenhum item é parcialmente alterado (Tarefa 3).
- Falha de rede/CSRF na seleção da galeria mantém a interface coerente e oferece o formulário existente como fallback (Tarefa 2).
- Assets sem grupo ou sem GPS continuam visíveis na galeria; nome confirmado nunca é confundido com `poi_final` inicial (Tarefa 1).

---

### Tarefa 1: Exibir o grupo confirmado na galeria

**Files:** modificar `src/drone_media_manager/api/routes/catalog.py`, `src/drone_media_manager/api/gallery.py`, `tests/integration/test_catalog_gallery.py` e `Docs/operations/gallery.md`.

**Interface:** acrescentar `location_group_id` e `location_group_name` ao payload de catálogo. Manter o campo `poi` como metadado inicial separado. Filtro de galeria: `group_id=<id>` ou `group_id=ungrouped`; validar que o grupo pertence à viagem. Buscar os nomes dos grupos uma vez por viagem, evitando consulta por card em listas com centenas de assets.

- [ ] Criar teste com dois assets da mesma viagem, um ligado a `LocationGroup(name_final="Baía dos Porcos")` e outro sem grupo/GPS; verificar payload, card, detalhe e filtro `ungrouped`. Criar também grupo de outra viagem para garantir isolamento.
- [ ] Rodar `uv run pytest tests/integration/test_catalog_gallery.py -q` e observar a falha nova.
- [ ] Implementar a consulta em lote dos grupos, enriquecer payload/card/detalhe e incluir seletor de grupo sem remover os filtros existentes.
- [ ] Rodar o teste alvo, `uv run ruff check .` e `uv run mypy src`; revisar a galeria com viagem sem grupos e com nomes acentuados.
- [ ] Atualizar o runbook da galeria e fazer commit `feat: show confirmed groups in gallery`.

### Tarefa 2: Selecionar um asset sem piscar a página

**Files:** modificar `src/drone_media_manager/api/gallery.py` e `tests/integration/test_phase_2d_auth.py`. Reusar `PUT /api/catalog/assets/{asset_id}/selection` em `src/drone_media_manager/api/routes/selection.py`; manter o POST do formulário como fallback sem JavaScript.

**Interface:** o PUT já recebe `{"selected": true|false}` com `X-CSRF-Token` e devolve `selected_count`. Após sucesso, atualizar botão, estado selecionado e contador no DOM. Atualizar a lista de downloads pelo endpoint existente `GET /api/catalog/trips/{slug}/selected-downloads`; exibir erro sem assumir que a seleção foi salva. Manter os links individuais de recuperação.

- [ ] Adicionar teste do contrato PUT para selecionar/desmarcar, CSRF inválido e contagem por usuário. Confirmar que o HTML conserva formulário POST e contém o comportamento progressivo.
- [ ] Rodar `uv run pytest tests/integration/test_phase_2d_auth.py -q` e observar a falha nova.
- [ ] Interceptar o envio apenas quando `fetch` estiver disponível; desabilitar o botão enquanto a requisição corre, restaurar estado em erro e reconstruir texto/links com APIs DOM seguras (`textContent`/`createElement`).
- [ ] Rodar testes alvo; testar num navegador real uma seleção, uma desmarcação, erro de rede e navegação sem JavaScript. Confirmar ausência de recarga e contador correto.
- [ ] Fazer commit `feat: update gallery selection without page reload`.

### Tarefa 3: Selecionar e desmarcar todos os assets exibidos

**Files:** modificar `src/drone_media_manager/catalog/selection.py`, `src/drone_media_manager/api/routes/selection.py`, `src/drone_media_manager/api/gallery.py` e `tests/integration/test_phase_2d_auth.py`.

**Interface:** criar `PUT /api/catalog/trips/{slug}/selection` com corpo `{"asset_ids": ["..."], "selected": true|false}`. Validar lista não vazia, IDs únicos, limite de 2000 e pertencimento integral à viagem antes de gravar. Aplicar inserção/remoção em uma transação; devolver `selected_count`. A página envia só os IDs dos cards exibidos, nunca os ocultos pelos filtros.

- [ ] Criar testes para 100 assets filtrados, repetição idempotente, usuário diferente, ID de outra viagem e ID inexistente; nos dois últimos, assertar que nenhuma seleção mudou.
- [ ] Rodar `uv run pytest tests/integration/test_phase_2d_auth.py -q` e observar a falha nova.
- [ ] Implementar operação em lote usando o constraint único existente de `AssetSelection`; adicionar botões **Selecionar exibidos** e **Desmarcar exibidos** e atualizar DOM/contador/lista de downloads como na Tarefa 2.
- [ ] Rodar teste alvo e testar manualmente dois filtros: desmarcar os exibidos não deve tocar nos selecionados ocultos. Confirmar CSRF e isolamento após logout/login de outro usuário.
- [ ] Fazer commit `feat: add filtered bulk selection`.

### Tarefa 4: Nome físico neutro para novas viagens no Windows

**Files:** modificar `src/drone_media_manager/cli/organize.py`, `src/drone_media_manager/organize.py`, `tests/integration/test_organize_local.py`, `Docs/operations/windows-organize.md` e `Docs/architecture/STORAGE_CONTRACTS.md`.

**Interface:** para viagens novas, `--poi` torna-se opcional; sem ele, usar a pasta inicial `a-classificar` e `location.poi_final=null`. Nomes físicos novos: `{data}_{source-stem-seguro}_{formato}_{id8}.mp4`, SRT com mesmo basename e foto com `_foto_{id8}`. Normalizar o stem da origem para caracteres seguros e limitar a 48 caracteres antes de anexar `id8`. `--movement` e `--people` continuam metadados opcionais, com default `None` no manifesto novo e sem `desconhecido` forçado no nome físico. O diretório inicial não representa grupo confirmado; `--poi` explícito preserva a pasta e o metadado inicial escolhidos pelo usuário.

**Compatibilidade:** adicionar `naming_scheme: "neutral-v1"` ao topo de novos manifestos schema 1. Manifestos existentes sem esse campo usam a regra antiga ao repetir PLAN/APPLY; o novo campo é opcional para o importador Mac. A função `_compatible_manifest` continua impedindo mudança de path ou hash do mesmo `asset_id`. Não migrar nem renomear `noronha-teste`.

- [ ] Criar testes de novo PLAN/APPLY sem `--poi`, MP4+SRT com basename idêntico, nome longo/inválido, hash/idempotência e ausência de `desconhecido` no basename. Repetir uma viagem criada com manifesto legado e assertar `CREATED=0`, caminhos iguais e manifesto intacto.
- [ ] Rodar `uv run pytest tests/integration/test_organize_local.py -q` e observar a falha nova.
- [ ] Implementar escolha de esquema por manifesto existente, nome neutro para viagem nova e metadados opcionais; manter cópia temporária, verificação SHA-256 e proteção contra conflito existentes.
- [ ] Rodar testes alvo, suíte completa, Ruff e mypy. Validar com mídia de teste nova no Windows/OMV e repetir PLAN/APPLY antes de qualquer importação no Mac.
- [ ] Atualizar contrato e runbook; fazer commit `feat: use neutral names for new organized trips`.

### Tarefa 5: Nome editorial somente na cópia baixada

**Files:** modificar `src/drone_media_manager/catalog/downloads.py`, `src/drone_media_manager/api/routes/downloads.py`, `src/drone_media_manager/api/gallery.py` e `tests/integration/test_phase_2d_downloads.py`.

**Interface:** quando houver grupo confirmado, compor `{data}_{grupo}_{movimento?}_{pessoas?}_{formato}_{id8}.{ext}`. Omitir campos ausentes ou `desconhecido`; não inferir movimento antes da 3C. Sem grupo, usar basename físico seguro. Incluir `id8` ao fim para unicidade e limitar cada parte antes da sanitização final. Usar o mesmo nome no `Content-Disposition`, na resposta `selected-downloads` e nos links da galeria. Bytes, caminho e hash do original não mudam.

- [ ] Criar teste com grupo `Baía dos Porcos`, sem grupo, dois nomes iguais, movimento/pessoas desconhecidos e caracteres proibidos. Confirmar header UTF-8, fallback ASCII, nome do preflight, bytes baixados iguais ao OMV e SRT/original preservados.
- [ ] Rodar `uv run pytest tests/integration/test_phase_2d_downloads.py -q` e observar a falha nova.
- [ ] Reusar `safe_filename` e `_content_disposition`; consultar `LocationGroup` apenas para o nome de download, sem renomear `AssetFile.rel_path`.
- [ ] Rodar testes alvo, suíte completa, Ruff e mypy; no Mac, baixar um original e comparar SHA-256 com o manifesto.
- [ ] Atualizar `Docs/operations/gallery.md` e fazer commit `feat: name downloaded copies from confirmed metadata`.

## Verificação e encerramento da próxima sessão

1. Rodar `uv run pytest tests/unit tests/integration tests/security -q`, `uv run ruff check .` e `uv run mypy src`. Conferir formatação dos arquivos alterados; a dívida anterior de formatação global não pertence a este plano.
2. Fazer backup do SQLite do Mac antes de atualizar o checkout. Testar galeria/seleção com viagem de dezenas de assets e o novo naming com **outra** viagem de teste; não repetir APPLY de `noronha-teste` para converter nomes.
3. Confirmar que filtros/seleção permanecem corretos após reinício, downloads são cópias com nome novo e hashes idênticos, e nenhum original ou grupo confirmado mudou.
4. Registrar resultados no checkpoint e publicar a branch para revisão. Decidir merge na `main` somente após o gate pré-3C aplicável.

# Drone Media Manager — diagnóstico funcional e prioridades

**Data:** 22/09/2026
**Projeto:** `C:\dev-apps\drone-orgnize`
**Revisão/commit auditado:** `1a1de0b3c26d420cdc4c954d0d3e8ccac7d11bd7` (`codex/phase-1-windows-omv`).

Auditoria do código, testes, migrations, CLI, manifesto produzido e destino de aceite acessível nesta máquina. O arquivo deste diagnóstico já era não rastreado antes da edição. “Implementado” descreve código existente; “testado” especifica o nível da evidência. O registro de aceite em `Docs/FASE_1_ACEITE_REAL_2026-09-22.md` é corroborado pelo manifesto e pela árvore de arquivos acessíveis em `P:\drone-organizado`, mas não substitui uma nova execução contra o hardware.

## 1. Resumo executivo atual

**A Fase 1 entrega uma CLI independente do Mac que lê uma pasta no Windows, pareia MP4/SRT, usa ffprobe para classificar vídeos, inclui JPG/JPEG, monta nomes editoriais, copia para um destino montado e publica `MANIFESTO.json`.** Há aceite documentado com mídia DJI real e destino OMV mapeado em `P:`; a auditoria atual leu o manifesto e encontrou seus 18 caminhos de mídia presentes. O aceite não demonstrou 4:3, quadrado, SRT órfão, `.jpeg`, falha de cópia, pouco espaço ou Mac importando os resultados.

**A Fase 2 ainda não foi implementada.** O servidor FastAPI/SQLite, migrations, worker e estruturas antigas de ingestão existem, mas a CLI editorial não os utiliza. Não há importador de manifesto, CRUD de viagens para usuário, catálogo editorial compatível, thumbnails/proxies, galeria, seleção persistida ou download. O worker atual só faz heartbeat/claim de jobs.

## 2. Arquitetura real e limites do fluxo

```text
Windows: pasta explícita → inventário recursivo MP4/SRT + JPG/JPEG
  → SHA-256 da origem + ffprobe dos MP4 → classificação
  → POI/movimento/pessoas informados globalmente na CLI → PLAN
  → APPLY: .partial → verificação SHA-256 → arquivo final
  → <output-omv>/<trip_slug>/MANIFESTO.json

Handoff existente: arquivos editoriais + manifesto no destino montado.
Mac: FastAPI + SQLite/Alembic + API técnica + worker de polling;
     nenhuma ligação com o manifesto editorial.
```

`dmm-organize` usa `build_plan`/`apply_plan` diretamente, sem `dmm-server`, SQLite, `Trip.id`, API ou worker. O pipeline legado de snapshots/ingestão aponta para `trips/<slug>/00_INBOX_ORIGINALS/...`; o organizador grava `<slug>/<poi>/<categoria>/...`. São contratos distintos, não etapas integradas do mesmo fluxo. A origem é lida por `FilesystemReadOnlySource`; não há remoção/formatação de fonte no organizador.

## 3. O que a Fase 1 realmente entrega

### Interface e entradas

Executável declarado em `pyproject.toml`: `dmm-organize`. Comandos reais:

```powershell
dmm-organize plan  --source <pasta> --trip <nome> --poi <nome> --output-omv <raiz> [--movement <valor>] [--people <valor>] [--date AAAA-MM-DD] [--ffprobe <executavel>]
dmm-organize apply --source <pasta> --trip <nome> --poi <nome> --output-omv <raiz> [mesmas opções]
```

`source`, `trip`, `poi` e `output-omv` são obrigatórios; movimento e pessoas começam em `desconhecido`. `--date` é data única para todos os assets. Não há entrada por asset/lote, edição interativa, seleção de arquivos nem descoberta de unidades na CLI; o caminho de pasta deve ser fornecido. `plan` e `apply` imprimem JSON; a CLI retorna 2 em `ERROR`, `CONFLICT` ou `errors`, e 0 no sucesso. Erros por arquivo são coletados com seu caminho e bloqueiam `apply` para o plano inteiro.

`PLAN` calcula SHA-256 integral de cada mídia suportada, invoca ffprobe para cada MP4, lê hashes de destinos existentes para mostrar `CREATE`, `ALREADY_OK` ou `CONFLICT`, e imprime `assets`, `files`, `orphan_srt`, `unsupported`, `errors` e `manifest_preview`. Não cria a pasta da viagem nem manifesto. Exige raiz de destino já existente e acusa `destination offline` caso contrário. Exige origem existente e diretório; rejeita sobreposição origem/destino. `manifest_preview` é previsão com `verification_status: PLANNED`, não evidência de cópia.

### Viagem e `trip_id`

No Windows, `--trip` vira `trip.name` e um `trip.slug` ASCII limitado a 60 caracteres por componente. `trip.external_id` é sempre `null`; não há `trip_id` no manifesto, nos paths ou nos nomes. O organizador não consulta o banco do Mac. O futuro importador poderá correlacionar `trip.slug` com `Trip.slug`, mas não existe tal importador, política de conflito ou migração de vínculo. Nomes diferentes que geram o mesmo slug disputam o mesmo diretório/manifesto; `_compatible_manifest` valida schema e slug, não o nome da viagem.

### Identidade do asset

`asset_id = SHA256(volume_identity + NUL + file_identity + NUL + source_sha256)`, em hexadecimal completo. `source_sha256` é SHA-256 **do conteúdo integral** do arquivo principal; `file_identity` vem de `st_dev:st_ino`; `volume_identity` deriva da raiz canônica da origem ou identidade UNC mapeada. Isso é distinto do fingerprint do inventário legado e distinto do hash do conteúdo sozinho. O ID não usa filename, path relativo, `trip_id`, POI ou tags diretamente. Com mesma raiz, mesmo arquivo físico e mesmo conteúdo, é determinístico e reaparece na segunda execução. Mover/copiar o arquivo para outra raiz ou sistema de arquivos, substituir o inode ou alterar bytes pode mudar o ID, mesmo com filename idêntico; renomear mantendo o mesmo inode/conteúdo tende a preservá-lo. A estabilidade de `st_ino` em toda mídia/driver Windows não foi validada. Colisões SHA-256 são teoricamente possíveis; colisões de prefixo de oito caracteres usado no basename são detectadas se gerarem o mesmo destino no plano, não resolvidas automaticamente. O Mac poderia guardar o ID para upsert, mas `MediaFile` não tem `asset_id` nem importador; sua deduplicação atual é outra (trip, tipo, tamanho e SHA-256).

MP4 com SRT é um asset lógico no manifesto: um `asset_id`, um registro, dois `PlannedFile` com o mesmo ID, hashes separados. Foto é outro asset lógico. SRT órfão não vira asset editorial.

## 4. Classificação técnica, MP4/SRT e fotos

### ffprobe e orientação

`probe_video` executa ffprobe real com `-v error -show_entries ... -of json`, timeout de 60 s, capturando código/saída. Escolhe o primeiro stream de vídeo e guarda `codec`, `duration_ms` (stream, senão formato), `fps` de `avg_frame_rate`, `encoded_width/height`, `rotation_degrees`, `display_matrix`, `display_width/height` e `creation_time`. A rotação vem de `side_data_list.rotation`, depois tag `rotate`, depois inferência pela matriz. Timeout, falha do processo ou JSON inválido geram erro daquele MP4 no plano; `apply` é bloqueado se houver erros. Não há fallback de classificação manual para vídeo que falha no probe.

Somente rotação ortogonal (0/90/180/270, tolerância de 0,01 grau) produz dimensões de exibição; 90/270 troca largura/altura. A regra exige proporção **exata**: largura × 9 = altura × 16 para `YOUTUBE_16X9`; altura × 9 = largura × 16 para `INSTAGRAM_9X16`; os demais são `OUTROS_REVISAR`. Não há crop, transcode ou orientação de fotos por EXIF. Os testes unitários cobrem explicitamente 3840×2160, 2160×3840, 3840×2160 com rotação 90°, 1920×1440, 1080×1080 e 45°; ffprobe/rotação e fallback de display matrix são testados com JSON sintético. No aceite real, dois vídeos 2688×1512 codificados foram exibidos em 1512×2688 por rotação de 90°; outros três eram 3840×2160. Não há aceite real dos cinco tamanhos da matriz sintética como conjunto.

### Sidecar DJI Flip

O inventário é recursivo e pareia `.mp4`/`.srt` pelo basename normalizado NFC e `casefold`, **na mesma pasta**. Identifica vídeo pareado, vídeo sem SRT e SRT órfão; nomes de mídia duplicados ignorando caixa geram erro. O SRT pareado é copiado com o mesmo basename editorial do MP4, extensão `.srt`, e aparece em `source.srt_status/name/path`, `output.srt_relative_path` e `output.srt_sha256`. Vídeo sem SRT segue com status `missing` e caminhos/hash SRT nulos. Órfão é listado em `orphan_srt`, não copiado. Nenhuma etapa do organizador apaga sidecar ou origem. **O conteúdo GPS do SRT não é parseado**; `location.gps_source` e `poi_suggested` ficam nulos. Teste de filesystem simulado cobre órfão; o aceite real teve quatro pares e um MP4 sem SRT, nenhum órfão.

### Fotos e ignorados

`.jpg` e `.jpeg` sem distinção de caixa entram como `FOTOS`, são hasheadas, nomeadas, copiadas e manifestadas; `video` é nulo, `movement`/`people` são nulos e SRT é `not_applicable`. Não há leitura de EXIF, orientação de foto, RAW/DNG ou geração de preview. Qualquer outra extensão (inclusive `.dng`) aparece em `unsupported` e não é copiada; arquivos não somem do relatório. O aceite real demonstrou nove `.JPG`; `.JPEG` e `.DNG` foram exercitados apenas por arquivos de bytes sintéticos em teste.

### Data e metadados editoriais

Prioridade da data: `--date` (`user`), `creation_time` do MP4 (`mp4_creation_time`), padrão `DJI_YYYYMMDDhhmmss_` no filename (`dji_filename`), depois `desconhecido` (`unknown`). Não se usa mtime como data de captura. `poi_final` guarda o texto passado à CLI; `poi_suggested` é nulo. Movimento e pessoas são valores globais transformados em slug, sem validação semântica, detecção visual ou telemetria. Não há geocoding.

## 5. Naming e diretórios

Cada campo de nome recebe NFKD → ASCII, minúsculas, sequência não alfanumérica substituída por hífen, hífens externos removidos, até 60 caracteres por componente; vazio após normalização é erro. Componentes exatamente reservados do Windows (`con`, `prn`, `aux`, `nul`, `com1..9`, `lpt1..9`) recebem `x-`. Isso evita caracteres inválidos nos componentes gerados; não há limite explícito para comprimento total de basename/path nem resolução automática de colisões. Valores desconhecidos tornam-se `desconhecido`. Extensões de vídeo viram `.mp4`; foto preserva `.jpg` ou `.jpeg` em minúsculas.

```text
<trip_slug>/<poi_slug>/YOUTUBE_16x9/<data>_<poi>_<movimento>_pessoas-<pessoas>_16x9_<asset_id[:8]>.mp4
<trip_slug>/<poi_slug>/INSTAGRAM_9x16/<data>_<poi>_<movimento>_pessoas-<pessoas>_9x16_<asset_id[:8]>.mp4
<trip_slug>/<poi_slug>/OUTROS_REVISAR/<data>_<poi>_<movimento>_pessoas-<pessoas>_outros_<asset_id[:8]>.mp4
<trip_slug>/<poi_slug>/FOTOS/<data>_<poi>_foto_<asset_id[:8]>.jpg
```

SRT usa exatamente o basename do vídeo e extensão `.srt`. Exemplo do aceite: `teste-fase-1/desconhecido/INSTAGRAM_9x16/2026-09-14_desconhecido_desconhecido_pessoas-desconhecido_9x16_0b1e95e0.mp4` e `..._0b1e95e0.srt`. Alterar POI/movimento/pessoas mantém `asset_id` no plano para mesma origem, mas altera path editorial; após publicação, `_compatible_manifest` rejeita republicar o mesmo ID em outro caminho. Não existe operação de renomeação editorial ou atualização de tags já publicadas.

## 6. PLAN/APPLY, idempotência e segurança da cópia

`APPLY` primeiro rejeita erros do plano, manifesto incompatível e destinos divergentes; compara fonte com o `SourceStat` inventariado. Cria diretórios abaixo da raiz resolvida por `RootMapper` e copia via `CopyEngine` para `.<nome>.<id8>.partial`, em blocos de 8 MiB com flush/fsync. Parcial existente só é retomado se seu prefixo coincide com a fonte. Compara o SHA-256 reportado pela cópia ao hash do plano, hasheia o parcial, renomeia para final e hasheia o final. Se arquivo final idêntico já existe, conta `ALREADY_OK`; divergente antes da cópia vira `CONFLICT` sem sobrescrita. O manifesto recebe `verification_status: VERIFIED`, funde assets anteriores por ID, é escrito em arquivo temporário com fsync e publicado por `os.replace`. Status final é `APPLIED` com contagens e caminho do manifesto.

| Situação | Estado comprovado |
|---|---|
| Segunda execução e destino idêntico | Implementado e testado em filesystem local; aceite real relata 0 criados/18 `ALREADY_OK` no segundo APPLY. |
| Destino divergente | Implementado e testado em filesystem local: `CONFLICT`, mantém bytes existentes. Não houve conflito induzido no OMV real. |
| Parcial coincidente/divergente e interrupção | Motor `CopyEngine` testado isoladamente com bytes sintéticos; o caminho editorial de falha/retomada não foi demonstrado com mídia real/OMV. |
| Fonte modificada | Checagens de stat antes/depois do hash/cópia e hash esperado; não há teste real de alteração concorrente durante APPLY. |
| Destino offline | `build_plan` acusa raiz não diretório; sem teste de queda do OMV no meio da cópia. |
| Pouco espaço | O preflight de capacidade existe no pipeline legado de ingestão, mas **não é chamado pelo organizador**; falha de disco fica como `OSError` durante APPLY. |
| Falha no meio do APPLY | Retorna `ERROR` e preserva arquivos/parciais já criados; não há rollback transacional da viagem. Manifesto só é publicado após o loop de arquivos. |

`PLAN` hasheia toda a origem e pode ser demorado; `APPLY` reconstrói o plano, repetindo hash/probe. A verificação de conflito antes de copiar não elimina corrida externa: o código usa `os.rename` para promover arquivo final, cuja semântica de substituição varia por plataforma. O caso de destino criado concorrentemente após a checagem não tem teste dedicado. Arquivo final previamente publicado é validado pelo hash do plano, mas não há uma nova revalidação global de todos os assets antigos ao fundir o manifesto. Não há reserva de espaço, transação entre arquivos nem teste de falha de energia.

## 7. OMV e evidência de aceite

`--output-omv` aceita um path existente; não há formato UNC obrigatório nem descoberta automática de compartilhamento. O aceite informa `P:\drone-organizado` mapeado a `\\OMV-SRV\VOL1_POOL_SSDs\drone-organizado`. O organizador usa esse path resolvido como raiz autorizada por `RootMapper`; não lê `DMM_OMV_ROOT` nem chama o preflight/capacidade legado. Não cria a raiz OMV, mas cria `<trip_slug>/<poi>/<categoria>` sob ela. `MANIFESTO.json` fica em `<output-omv>/<trip_slug>/MANIFESTO.json`.

O registro de aceite de 22/09/2026 declara quatro comandos (PLAN/APPLY duas vezes): 18 CREATE/CREATED na primeira, 18 ALREADY_OK na segunda, zero conflitos/erros; 14 assets (2 verticais por rotação, 3 horizontais, 9 fotos); quatro SRT preservados e um vídeo sem SRT; conferência `Get-FileHash` 18/18 entre origem, destino e manifesto. **Nesta auditoria**, o manifesto real acessível tem `schema_version=1`, 14 registros `VERIFIED`, 18 paths de mídia existentes, distribuição física 5 MP4 + 4 SRT + 9 JPG, e nenhum `.partial` sob a viagem. Não repeti o hash integral dos 18 arquivos nem os comandos PLAN/APPLY sobre a mídia real. O registro do aceite e a presença atual dos arquivos sustentam execução contra o destino OMV mapeado, não apenas pasta local simulada; não comprovam disponibilidade contínua ou acesso do Mac a esse compartilhamento.

## 8. Contrato real de handoff Windows → Mac

O manifesto real inspecionado é JSON `schema_version: 1`, com `trip: {name, slug, external_id: null}`, `assets: []`, `orphan_srt: []` e `unsupported: []`. Cada asset contém:

| Grupo | Campos efetivos / interpretação |
|---|---|
| Identidade | `asset_id` hexadecimal; `trip.name/slug/external_id` repetidos em cada asset. Sem `trip_id`. |
| Origem | `source.video_name/path` ou `photo_name/path`, `srt_status/name/path`, `source_sha256`. Paths absolutos Windows são informação histórica, não paths que o Mac possa abrir. |
| Vídeo | Objeto `video` com codec, duração ms, FPS, dimensões codificadas/exibidas, rotação, matriz e `creation_time`; `null` para foto. |
| Classificação | `YOUTUBE_16X9`, `INSTAGRAM_9X16`, `FOTOS` ou `OUTROS_REVISAR`. |
| Local/editorial | `location.gps_source: null`, `poi_suggested: null`, `poi_final`; `editorial.movement/people/capture_date/capture_date_source`. |
| Saída | Um de `video_relative_path`/`photo_relative_path`; `srt_relative_path` opcional; `sha256` principal, `srt_sha256` opcional; `verification_status`. Paths relativos à raiz `output-omv`, não ao diretório do manifesto. |

Exemplo curto do artefato real: o vídeo com `asset_id` iniciado em `0b1e95e0` é `INSTAGRAM_9X16`, codificado 2688×1512, exibido 1512×2688 com rotação 90°, `duration_ms=20479`, `fps=23.97602`, `codec=hevc`, SRT pareado e dois caminhos editoriais de mesmo basename; `capture_date_source=mp4_creation_time` e `verification_status=VERIFIED`. Uma foto de ID iniciado em `0273cce2` tem `video=null`, `classification=FOTOS`, data oriunda de `dji_filename`, saída `.jpg`. Os hashes completos e paths de origem constam no manifesto; os IDs acima são apenas prefixos para leitura.

O Mac poderá ler slug, ID, classificação, metadados, tags, hashes e paths de saída **se for criado um importador**. O contrato não traz tamanho do arquivo, MIME, data EXIF da foto, GPS parseado, lat/lon, ID de Trip no SQLite, revisão/timestamp do manifesto, estado de importação, thumbnail/proxy ou seleção. O manifesto diz `VERIFIED` para a cópia no Windows; não atesta que o Mac consegue abrir o arquivo ou que houve importação.

## 9. Fundação Mac/SQLite/API/worker para receber a Fase 2

- **Servidor e SQLite:** `dmm-server run/migrate`, FastAPI/Uvicorn, SQLAlchemy e Alembic 0001/0002. Configuração `DMM_` separa SQLite local da raiz OMV, rejeita banco em UNC/OMV/sync; conexão usa foreign keys, busy timeout e WAL; startup verifica revisão da migration e recupera leases expirados. Testes usam banco temporário; não há evidência de instância Mac em produção nesta auditoria.
- **Trip:** tabela `trips`: UUID `id`, `name`, `slug` único, `nas_rel_path` único, `created_at`, `updated_at`. `IngestJob` e `MediaFile` referenciam `trip_id`; `MediaPair` também. Testes criam Trip diretamente no banco para confirmação de ingestão. Não há rota CRUD de Trip, importação por slug ou relação ORM navegável declarada. `nas_rel_path` do legado não é preenchido pelo organizador.
- **MediaFile/catálogo:** tabela `media_files`: UUID `id`, `trip_id`, `ingest_item_id` obrigatório, `original_filename`, `rel_path`, `media_type`, `size_bytes`, `sha256`, `created_at`; unique `(trip_id, media_type, size_bytes, sha256)`. `record_verified_media` depende de um `IngestItem` prévio. Não há `asset_id`, classificação, codec, duração, FPS, dimensões, rotação, data/fonte, POI, movimento, pessoas ou referência a proxy/thumbnail; importação direta do manifesto não cabe no modelo atual sem adaptar persistência/migration ou criar estados legados.
- **Sidecars:** `MediaPair` contém `trip_id`, IDs opcionais de MediaFile para vídeo/SRT e `pair_status`; não modela `srt_sha256` no asset lógico da Fase 1 nem tem consumidor de manifesto. Não há parser SRT.
- **API e autenticação:** rotas reais são `/health`, `/api/workers`, `/api/worker-jobs`, `/api/sources/snapshots` e `/api/ingests`. Worker usa token bearer/bootstrap; confirmação de ingestão depende de bind loopback, não de login de usuário. Não há autenticação de esposa/usuário, viagens/assets editoriais, publicação/consulta de manifesto, serving de originais por `asset_id`, HTTP Range ou download.
- **Worker/fila:** `Job` persiste status, tentativas, lease, revisão e progresso; API permite claim/progress/complete/fail. `WorkerService.run_once` só heartbeat e claim, retorna `CLAIMED`/`IDLE`; não despacha ingestão, organiza mídia, importa manifesto ou gera derivados.
- **Produto Mac:** não existe frontend, galeria, thumbnail, proxy, seleção/review persistente ou download individual/lote. Não há código de leitura do manifesto no servidor.

## 10. Matriz desejo × implementação atual

| Necessidade | Estado agora | Evidência e limite |
|---|---|---|
| Pasta/unidade Windows | Implementado via path explícito | `dmm-organize --source`; descoberta de removível existe separada, sem UI/integração na CLI. |
| Viagem | Parcial | Nome/slug e diretório/manifesto no Windows; Trip SQLite existe, sem CRUD/importação. |
| Vídeos MP4 | Implementado e aceito com mídia real | Cinco MP4 no aceite; sem catálogo Mac. |
| SRT | Parcial | Pareamento/cópia/hash real de quatro pares; órfão só listado, GPS não parseado. |
| Fotos JPG/JPEG | Parcial | JPG real no aceite; JPEG sintético; sem EXIF/RAW/preview. |
| ffprobe | Implementado e aceito com mídia real | Metadados no manifesto; timeout/erro por arquivo no código. |
| 16:9 e 9:16 | Implementado e aceito com mídia real | Três horizontais e dois verticais por rotação; proporção exata. |
| Outros formatos | Implementado em classificação, sem aceite real | 4:3/quadrado em unitários; pasta `OUTROS_REVISAR`. |
| POI manual | Parcial | CLI global e `poi_final`; sem edição por asset/lote após publicação. |
| GPS/SRT e geocoding | Ausente | Sidecar preservado, sem parser/API geográfica; campos de sugestão nulos. |
| Movimento e pessoas | Parcial manual | Valores globais no CLI/manifesto; sem detecção ou correção por asset. |
| Naming | Implementado | Paths editoriais e mesmo basename MP4/SRT; sem limite total/renomeação posterior. |
| Manifesto | Implementado | Schema 1 produzido no OMV; nenhum importador. |
| OMV | Implementado no aceite Windows | Destino P: mapeado e arquivos presentes; Mac não verificado. |
| Idempotência/conflitos | Parcial | Segunda execução real idêntica; conflito testado localmente, sem conflito real no OMV. |
| Galeria | Ausente | Sem frontend/rotas. |
| Thumbnails/proxies | Ausente | Sem geradores, persistência ou serving. |
| Seleção/reviews | Ausente | Sem tabela/rotas/UI. |
| Download/HTTP Range | Ausente | Sem endpoint de arquivos/lote. |
| Mac com Windows offline | Não demonstrado | OMV tem originais; falta catálogo/previews/API e teste com Windows desligado. |
| Windows offline durante uso do Mac | Não demonstrado | Nenhum fluxo de importação/publicação no Mac. |

## 11. Estado das fases

| Fase | Estado | Evidência e limite |
|---|---|---|
| 0 — Fundação | Entregue como componentes, integração operacional parcial | FastAPI/SQLite/Alembic, worker, fila, segurança e testes; worker não executa mídia. |
| 1 — Windows → OMV / classificação + naming | Entregue no escopo da CLI, com limites | Commit `a2b97db`, nove testes específicos, aceite documentado `1a1de0b` e manifesto/18 arquivos acessíveis; sem GPS, edição por asset, pouco espaço/falha real, Mac. |
| 2 — OMV → Mac / catálogo + galeria + seleção + download | Não iniciada como fluxo | Modelos e API técnica da fundação existem; nenhum importador/galeria/seleção/download. |
| 3 — automação via GPS/SRT/telemetria | Não iniciada | SRT só é preservado; campos GPS/sugestão nulos. |
| 4 — selects/retenção | Não iniciada | Sem modelos, UI ou operações de retenção/selects. |

## 12. Testes e níveis de evidência

Execuções nesta auditoria, 22/09/2026, no ambiente virtual existente:

| Comando | Resultado | Escopo |
|---|---|---|
| `.venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/security -q` | **182 passed, 1 skipped, 52 warnings**, 14,54 s | Suite geral; SQLite/API/filesystem temporários, mocks e bytes sintéticos. |
| `.venv\Scripts\python.exe -m pytest tests/unit/test_organize_classification.py tests/unit/test_organize_cli.py tests/integration/test_organize_local.py -q` | **9 passed**, 0,67 s | Fase 1: regras, ffprobe simulado, PLAN, cópia local, idempotência e conflito. |
| `.venv\Scripts\ruff.exe check .` | **All checks passed** | Lint. |
| `.venv\Scripts\python.exe -m mypy src` | **Sem problemas em 56 source files** | Tipagem estática. |
| `.venv\Scripts\ruff.exe format --check .` | **Falhou: 26 arquivos seriam reformatados; 79 formatados** | Gate global, inclusive código nos arquivos Markdown de planos; não foi alterado. |

O skip é de symlink indisponível neste Windows; warnings incluem deprecações de FastAPI/Starlette. Os testes de classificação são unitários; o teste `test_organize_local.py` usa filesystem real temporário com MP4/JPEG/SRT de **bytes sintéticos** e monkeypatch de ffprobe, não mídia reproduzível. O aceite `Docs/FASE_1_ACEITE_REAL_2026-09-22.md` é uma execução separada com mídia DJI real e OMV real mapeado; não é um teste automatizado E2E. Nesta auditoria, o manifesto e 18 destinos foram rechecados quanto a presença, não quanto a hash integral.

Matriz de aceite real: horizontal **sim** (3); vertical por rotação **sim** (2); DJI MP4+SRT **sim** (4 pares); MP4 sem SRT **sim** (1); JPG **sim** (9); primeira e segunda execução **sim**, com 18 `ALREADY_OK` na segunda; conflito **não induzido** no OMV (somente teste local); SRT órfão, JPEG, 4:3/quadrado e falha de destino **não demonstrados com mídia real**. Mac, SQLite e UI não participaram desse aceite.

## 13. Limitações da auditoria

A verificação atual foi feita no checkout Windows e no `P:` montado. Não executei o serviço no Mac, não verifiquei sua base de dados nem autenticação de usuários, não forcei falha de rede/disco, falta de espaço, concorrência ou reprocessamento de uma viagem com tags alteradas. O manifesto contém paths absolutos da origem Windows; eles não validam acessibilidade pelo Mac. O aceite registra hashes 18/18, mas esses hashes não foram recalculados nesta auditoria. `git status` já mostrava este diagnóstico e outros documentos não rastreados; só este arquivo foi editado.

## 14. Mapa de evidências

Caminhos relativos à raiz do projeto; linhas/símbolos no HEAD auditado.

| Fonte | Símbolo/linhas | Teste ou evidência correspondente |
|---|---|---|
| `pyproject.toml` | `[project.scripts]` | Executável `dmm-organize` instalado no aceite. |
| `src/drone_media_manager/cli/organize.py` | `_parser` 12–24; `main` 26–44 | `tests/unit/test_organize_cli.py` 11–39. |
| `src/drone_media_manager/organize.py` | `display_dimensions` 12; `classify_video` 27; `probe_video` 38 | `tests/unit/test_organize_classification.py` 10–78; manifesto real. |
| Mesmo módulo | `_slug` 152; `_hash_source` 170; `build_plan` 253–448 | `tests/integration/test_organize_local.py` 38–158; exemplos do aceite. |
| Mesmo módulo | `OrganizePlan.preview` 203–250; `_compatible_manifest` 451; `apply_plan` 492–588 | `test_organize_cli.py`; `test_organize_local.py` 73–113; PLAN/APPLY do aceite. |
| `src/drone_media_manager/ingest/inventory.py` | `build_inventory` 61; `_inventory_item` 90 | `tests/unit/test_inventory.py`; quatro pares reais no manifesto. |
| `src/drone_media_manager/sources/paths.py` | `validate_source_entry` 33; `file_identity` 69; `_source_identity` 74 | `tests/security/test_source_paths.py`. |
| `src/drone_media_manager/sources/discovery.py` | `FilesystemReadOnlySource`; `source_from_explicit_path` | `tests/unit/test_source_discovery.py`; origem do aceite. |
| `src/drone_media_manager/ingest/copy.py` | `CopyEngine.copy_or_resume`; `_assert_prefix` | `tests/unit/test_chunked_copy.py`; `tests/integration/test_copy_resume.py`. |
| `src/drone_media_manager/storage/roots.py` | `LogicalMediaPath.parse`; `RootMapper` | `tests/unit/test_storage_roots.py`; caminhos do manifesto. |
| `Docs/FASE_1_ACEITE_REAL_2026-09-22.md` | Comandos, matriz e hashes declarados | `P:\drone-organizado\teste-fase-1\MANIFESTO.json`: schema 1, 14 assets, 18 paths presentes. |
| `src/drone_media_manager/config.py` e `db/session.py` | `ServerSettings`; `create_engine_from_settings` | `tests/unit/test_config.py`; `tests/integration/test_migrations.py`. |
| `src/drone_media_manager/db/models/ingest.py`; `db/migrations/versions/0002_ingest.py` | `Trip` 29; `MediaFile` 190; `MediaPair` 219; migration `upgrade` | `tests/integration/test_ingest_migration.py`; `test_ingest_repository.py`. |
| `src/drone_media_manager/api/app.py` | `create_app` 85–126 | `tests/integration/test_health.py`, `test_ingest_confirmation_api.py`, `test_worker_api.py`. |
| `src/drone_media_manager/api/routes/ingests.py` | `confirm_ingest` 57; `_destination_path` 161 | `tests/integration/test_ingest_confirmation_api.py`; contrato legado diferente. |
| `src/drone_media_manager/worker/service.py` | `WorkerService.run_once` 39 | `tests/unit/test_worker_service.py`; ausência de dispatch de mídia. |
| `src/drone_media_manager/ingest/preflight.py` | `run_preflight` 33 | `tests/unit/test_ingest_preflight.py`; não chamado por `organize.py`. |

## Lacunas técnicas e funcionais antes da Fase 2

Esta lista identifica distância factual até **OMV → import manifest → SQLite → Trip/assets → thumbnail/proxy → galeria → seleção → download**; não é plano de implementação.

1. O manifesto tem `trip.slug`, mas não `trip_id`/`external_id`; `Trip` exige UUID e `nas_rel_path`, e não há importador/correlação nem CRUD de viagens.
2. O manifesto tem `asset_id`, classificação, vídeo, POI, movimento, pessoas, data e fonte; `MediaFile` guarda apenas identidade do fluxo legado, caminho, tipo, tamanho e hash. Falta persistência compatível/migration para esses metadados e regra de upsert por `asset_id`.
3. `MediaFile.ingest_item_id` é obrigatório e `record_verified_media` requer `IngestItem`; assets editoriais produzidos fora da fila não têm esse registro.
4. Paths da Fase 1 são `<slug>/<poi>/<categoria>/...`; confirmação antiga de ingestão usa `trips/<slug>/00_INBOX_ORIGINALS/...`. Não há mapeamento publicado do path relativo do manifesto para a raiz OMV do Mac.
5. O manifesto preserva SRT e hash, mas a relação `MediaPair` não é populada pelo organizador; não há importação ou parser de telemetria.
6. Fotos não trazem EXIF/tamanho/MIME no manifesto; o Mac não tem derivados para JPG/JPEG e não há tratamento RAW.
7. Não há geração, armazenamento ou serving de thumbnails/proxies, nem galeria/frontend ou endpoint de originais com HTTP Range.
8. Não há login/autorização de usuários finais, seleção/review persistente, endpoint para seleção ou download individual/lote.
9. O worker/fila legados não executam o organizador nem importam manifesto; o sucesso Windows não atualiza SQLite do Mac.
10. Não foi demonstrado que o Mac lê `P:`/UNC equivalente, nem operação com Windows desligado ou tratamento de OMV offline para navegação/download.

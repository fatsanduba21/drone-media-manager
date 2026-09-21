# Drone Media Manager — Especificação técnica e plano de implementação

> Documento para execução pelo Codex, em português (Brasil). Versão inicial: 2026-09-21.
> **Instrução principal:** implemente incrementalmente, com testes e checkpoints. Não trate hipóteses de qualidade visual ou identificação de POI como fatos.

## 0. Como usar este documento no Codex / Superpowers

1. Leia este documento integralmente e inspecione o repositório antes de modificar qualquer arquivo.
2. Se a skill **Superpowers** estiver instalada, utilize o fluxo de brainstorming/spec review → `writing-plans` → `executing-plans` ou `subagent-driven-development`, com TDD e revisão. Não presuma que a skill está disponível: confirme.
3. Primeiro apresente um plano de implementação granular, mapeado às fases abaixo, e identifique decisões realmente bloqueantes. Não reinvente decisões já fechadas.
4. Execute **uma fase por vez**, com testes automatizados, revisão de segurança e relatório de resultados. Não avance para exclusão real sem autorização expressa.
5. Nunca trabalhe diretamente sobre o cartão: a origem é somente leitura do ponto de vista do aplicativo. Não formate nem apague o cartão.

### Prompt inicial sugerido

```text
Leia DRONE_MEDIA_MANAGER_SPEC_AND_PLAN.md integralmente. Inspecione o repositório e identifique o estado atual. Se Superpowers estiver disponível, aplique seu fluxo de planejamento detalhado e TDD. Antes de codificar, proponha a árvore de arquivos, interfaces, migrações e um plano em tarefas pequenas para a Fase 0 e Fase 1, com critérios de aceite e comandos de teste. Respeite os invariantes de segurança do documento. Não implemente todas as fases de uma vez. Aguarde minha aprovação do plano antes de começar.
```

## 1. Contexto, objetivo e decisões fechadas

O usuário filma com um **DJI Flip**, insere o cartão microSD de **128 GB** em leitor USB no PC (tipicamente `E:\` ou `F:\`), importa o material, e sua esposa seleciona os vídeos e trechos que merecem edição no CapCut para YouTube (16:9) e Instagram (9:16). O problema inclui acúmulo de mídia bruta, tempo de triagem e custo/volume no iCloud.

**Decisões fechadas:**

- Host de aplicação/processamento: **Windows 11**, computador principal.
- Mídia: **NAS via compartilhamento SMB** na rede doméstica. Configurar caminho UNC (`\\servidor\share\...`); não fixar letra de unidade.
- Banco: **SQLite em disco local do Windows**, nunca arquivo SQLite ativo em SMB ou iCloud.
- Motor: Python, `ffprobe`, `ffmpeg`; outras bibliotecas pequenas apenas quando justificadas.
- Interface: web responsiva para **qualquer dispositivo na LAN**; processamento e acesso aos arquivos ocorrem no servidor, não nos clientes.
- Decisão final sobre retenção e exclusão: humana (usuário/esposa).
- Hermes não faz parte desta versão. Nenhum serviço de IA na nuvem é requisito.

**Objetivo:** ingestão confiável → catálogo → proxies → análise e sugestões explicáveis → revisão humana → selects de qualidade → retenção/limpeza segura → biblioteca curada para iCloud.

**Não objetivos iniciais:** editar no CapCut automaticamente; identificar POIs sem serviço/mapa apropriado; publicar em redes sociais; apagar cartão automaticamente; garantir julgamento artístico automatizado; sincronizar automaticamente com iCloud por API não suportada.

## 2. Princípios e invariantes de segurança

1. **SD read-only:** nenhuma operação de rename, move, delete ou write no cartão. A formatação final é manual no DJI.
2. **Cópia antes da análise:** processamento somente em cópia no NAS ou área local de staging. Nunca abrir mídia do cartão para geração de proxies ou cortes.
3. **Ingestão verificável:** inventário, tamanho, hash SHA-256 da origem e do destino, status persistido e retomada. Arquivo parcial recebe extensão temporária e rename atômico no mesmo volume ao concluir.
4. **Originais imutáveis durante processamento:** não recodificar, sobrescrever ou renomear MP4/SRT importados.
5. **Sem exclusão automática:** classificação `REJECT` é proposta; não equivale a exclusão física. Exigir prévia, confirmação explícita e validações de dependências e integridade.
6. **Sem exclusão do último exemplar:** verificar destino e hashes antes de remover qualquer original temporário. Nunca afirmar que iCloud está sincronizado apenas por existência em pasta local.
7. **Operações idempotentes:** reimportar o mesmo cartão não duplica registros nem sobrescreve arquivo divergente. Reexecução retoma operações interrompidas.
8. **Auditoria:** toda decisão humana e operação de arquivo gera evento com horário, usuário/ator e resultado.
9. **Falha segura:** se NAS cair, espaço faltar, hash divergir, SRT faltar ou processo interromper, sinalizar erro e preservar origem e arquivos válidos.
10. **LAN somente:** sem exposição pública, UPnP ou port forwarding automático; proteger operações destrutivas contra CSRF e acesso não autorizado.

## 3. Fluxo operacional

```text
SD em leitor USB (E:/F:) — somente leitura lógica
  → detectar e inventariar MP4/SRT (incluindo pares faltantes)
  → selecionar/criar viagem e destino NAS
  → checar espaço, permissões e conectividade
  → copiar para INBOX temporária; hash e manifesto
  → liberar cartão para formatação MANUAL após cópia íntegra e política de segurança atendida
  → ffprobe + SRT + catalogação
  → proxies H.264 compatíveis com navegador + thumbnails
  → classificação técnica e candidatos a takes
  → revisão humana via LAN
  → gerar selects e validar outputs
  → relatório de retenção / exclusão pendente
  → aprovação explícita → limpeza de INBOX quando segura
  → biblioteca curada para edição/arquivo e eventual iCloud
```

**Importante:** o cartão de 128 GB não deve ficar preso até a edição final. Após ingestão íntegra e existência de cópia segura, a UI pode mostrar `CÓPIA VALIDADA — cartão pode ser formatado manualmente`, com aviso de que isso reduz redundância caso só exista uma cópia no NAS. Oferecer política configurável de backup adicional antes de liberar cartão. Não exigir sincronização iCloud para liberar cartão; não confundir liberar cartão com autorizar apagar INBOX.

## 4. Arquitetura

```text
[Browser PC/iPad/iPhone/TV]
        | HTTP na LAN (autenticado)
        v
[FastAPI + UI responsiva] ---- [SQLite local Windows]
        |
        +---- [fila de jobs persistida / worker Python]
        |             +-- ffprobe
        |             +-- ffmpeg
        |             +-- parser SRT
        |             +-- métricas / sugestões
        |
        +---- [NAS SMB: originais, proxies, thumbnails, selects, exports]
        +---- [SD removível: leitura SOMENTE durante ingestão]
```

**Stack recomendada:** Python 3.12+; FastAPI, Uvicorn, SQLAlchemy + Alembic (ou sqlite3 + migrações próprias, decidir uma abordagem e manter consistência), Pydantic, Jinja2/HTMX ou JS leve, pytest. `ffmpeg`/`ffprobe` instalados e verificados no startup. Usar subprocess com lista de argumentos, sem `shell=True`. Fila inicial: tabela SQLite + worker único ou pool limitado; não exigir Redis/Celery.

O banco local não deve ser acessado diretamente por clientes da LAN. Ativar foreign keys, busy timeout, migrações e backups consistentes pela API SQLite. Avaliar WAL somente em disco local. Mídia pode residir em UNC; configurar timeouts, retries e concorrência limitada para não saturar o NAS.

## 5. Estrutura de diretórios proposta

```text
repo/
  pyproject.toml
  README.md
  .env.example
  docs/
    architecture.md
    operations.md
    testing.md
  src/drone_media_manager/
    config.py
    cli.py
    db/{models.py,session.py,migrations/}
    ingest/{discovery.py,inventory.py,copy.py,verify.py,manifest.py}
    metadata/{ffprobe.py,srt.py,orientation.py,gps.py}
    analysis/{motion.py,technical.py,similarity.py,segments.py}
    media/{proxy.py,thumbnail.py,select.py}
    jobs/{models.py,worker.py}
    api/{app.py,routes/}
    web/{templates/,static/}
    retention/{policy.py,planner.py,executor.py}
    storage/{paths.py,nas.py,backup.py}
  tests/{fixtures/,unit/,integration/,e2e/}
```

```text
NAS_ROOT/
  trips/2026-08_monte-verde_<trip-id>/
    00_INBOX_ORIGINALS/        # temporário, MP4/SRT originais intocados
    01_PREVIEWS/               # proxies e thumbnails regeneráveis
    02_SELECTS/
      YOUTUBE_16x9/
      INSTAGRAM_9x16/
    03_KEEP_ORIGINALS/         # retenção permanente quando aprovada
    04_EXPORTS/
    05_MANIFESTS/              # manifesto e relatórios JSON/CSV
    99_QUARANTINE/             # opcional, retenção temporária antes de purge
```

Não duplicar original entre INBOX e KEEP sem contabilizar custo: operação segura de promoção/movimentação no mesmo filesystem quando apropriado, preservando hash e rollback. Caminhos no banco devem ser relativos à raiz configurada sempre que possível; não depender da letra de unidade do SD.

## 6. Modelo de dados SQLite (proposta inicial)

Todas as tabelas principais: UUID/ULID ou IDs estáveis, `created_at`, `updated_at` UTC, índices adequados e foreign keys.

| Tabela | Campos centrais / propósito |
|---|---|
| `trips` | `id`, `slug`, `name`, `date_start`, `date_end`, `nas_rel_path`, `status` |
| `ingest_jobs` | `id`, `trip_id`, `source_volume`, `source_fingerprint`, `status`, `bytes_total`, `bytes_verified`, `error`, timestamps |
| `media_files` | `id`, `trip_id`, `original_filename`, `rel_path`, `media_type`, `size_bytes`, `sha256`, `duration_ms`, `codec`, `width`, `height`, `rotation_deg`, `display_width`, `display_height`, `fps_num`, `fps_den`, `captured_at_utc`, `status` |
| `media_pairs` | `video_id`, `srt_id`, `pair_status`; SRT ausente é permitido |
| `telemetry_samples` | `video_id`, `t_ms`, `lat`, `lon`, `rel_alt_m`, `abs_alt_m`, `gimbal_yaw_deg`, `gimbal_pitch_deg`, demais campos opcionais; estratégia de downsampling/configuração |
| `media_analysis` | `video_id`, `analyzer_version`, `gps_distance_m`, `net_displacement_m`, `altitude_delta_m`, `yaw_delta_deg`, `orientation`, `movement_labels_json`, `confidence_json`, `warnings_json` |
| `locations` | `id`, `name`, `lat`, `lon`, `source`, `confidence`, `user_override`; geocoding opcional/cacheado |
| `takes` | `id`, `video_id`, `start_ms`, `end_ms`, `source`, `technical_metrics_json`, `tags_json`, `status` |
| `reviews` | `id`, `take_id` ou `video_id`, `actor`, `decision`, `notes`, `reviewed_at`, `revision` |
| `assets` | `id`, `source_video_id`, `take_id` opcional, `kind` (proxy/thumbnail/select/export), `rel_path`, `sha256`, `size_bytes`, `status` |
| `jobs` | `id`, `kind`, `payload_json`, `status`, `attempts`, `progress`, `error`, timestamps |
| `file_operations` | `id`, `kind`, `source`, `destination`, `preconditions_json`, `approval_id`, `status`, `result_json`, timestamps |
| `audit_events` | `id`, `actor`, `action`, `entity_type`, `entity_id`, `details_json`, `occurred_at` |

**Estados sugeridos:** ingest `DISCOVERED → COPYING → VERIFYING → VERIFIED` ou `FAILED/INTERRUPTED`; análise `PENDING → RUNNING → COMPLETE/FAILED`; review `UNREVIEWED → KEEP_ORIGINAL/KEEP_SELECT/REVIEW_LATER/REJECT`; arquivo `ACTIVE → PENDING_DELETE → QUARANTINED → PURGED`. Validar transições no backend; nenhuma alteração de UI deve contornar a política.

## 7. Requisitos funcionais

### RF-01: Detecção e ingestão

- Listar unidades removíveis candidatas; confirmar explicitamente origem e viagem. Aceitar caminho manual (para testes e Mac futuro).
- Recursão configurável em `DCIM`; reconhecer extensões sem diferenciar maiúsculas/minúsculas; MP4/SRT pelo stem completo. Não assumir que todo vídeo tem SRT.
- Inventário antes de copiar; espaço livre com margem configurável; detectar nomes repetidos, arquivos incompletos e mudança do cartão durante cópia.
- Copiar em chunks com progresso e cancelamento seguro; registrar hashes e verificar origem/destino. Reinício não sobrescreve conteúdo diferente.
- Exportar `ingest_manifest.json` com IDs, paths relativos, tamanhos, hashes, pareamento e erros.

### RF-02: Metadados, SRT e GPS

- `ffprobe` JSON com timeout; usar `Fraction` para FPS. Registrar codec, duração, resolução codificada e matriz de exibição.
- Orientação deve considerar `side_data_list` / display matrix e rotação; não inferir apenas por `width > height`.
- Parser SRT tolerante a campos opcionais, cue irregular, timezone e dados ausentes. Para alinhamento, preferir tempo relativo do cue; validar diferença de duração com MP4. Preservar SRT bruto.
- Calcular distância percorrida com filtro de jitter, deslocamento líquido, variação de altitude, yaw desembrulhado (`unwrap`) e alertas de qualidade. **Gimbal yaw não é heading da aeronave**.
- POI: inicialmente coordenadas + agrupamento geográfico + nome manual. Geocoding externo somente com integração opcional, limites e cache; não inventar local exato.

**Fixtures conhecidas para regressão (validar contra anexos reais disponíveis):**
- `DJI_20260828155700_0011_D`: horizontal 3840×2160, ~29.97 fps, ~34.5 s; trajetória próxima de círculo, yaw ~−351.8° desembrulhado; candidato a órbita, não certeza apenas pelo yaw.
- `DJI_20260830152014_0002_D`: codificado 2688×1512 com rotação +90°, exibição 1512×2688 (9:16), ~23.976 fps.
- `DJI_20260830152121_0003_D`: horizontal 3840×2160, ~23.976 fps, movimento lento com descida.
- `DJI_20260830151818_0001_D`: horizontal 3840×2160, ~63.02 s, MP4 timestamp UTC coerente com horário local −03:00.

Esses valores são exemplos de aceitação; fixtures pequenas/anônimas devem permitir CI sem depender dos MP4 originais grandes.

### RF-03: Proxies e thumbnails

- Gerar proxy H.264 + AAC se áudio existir, `yuv420p`, MP4 com `+faststart`, resolução configurável (ex.: 720p), rotação aplicada corretamente para exibição web.
- Preservar proporção, sem esticar vertical. Thumbnail representativo; geração idempotente por versão de parâmetros.
- Processar com concorrência limitada, timeout e cancelamento; não bloquear request HTTP.
- Entregar por endpoints autenticados com suporte a HTTP Range para seek; evitar path traversal e leitura arbitrária do NAS.

### RF-04: Análise e sugestões

- V1: tags de orientação e movimento a partir da telemetria; valores `UNKNOWN` quando insuficiente.
- Órbita exige evidência combinada de trajetória aproximadamente circular, cobertura angular e rotação; panorâmica estacionária não deve virar órbita.
- Métricas técnicas opcionais (blur, exposição, tremor) devem ser calibradas e explicitamente rotuladas como heurísticas; não atribuir `smooth` ou score de qualidade sem cálculo.
- Sugestão de takes pode começar manual; algoritmos de segmentação e redundância entram em fase posterior. Não excluir por score.
- Registrar versão do algoritmo, evidências e confiança. Usuário pode corrigir tags e limites de takes.

### RF-05: UI de revisão

- Lista de viagens e dashboard de ingestão/armazenamento.
- Grade de vídeos com thumbnail, duração, orientação, tags, status e filtros.
- Player proxy com seek e controles de `in/out` em milissegundos; preview do trecho e comparação entre tomadas.
- Decisões: `KEEP_ORIGINAL`, `KEEP_SELECT`, `REVIEW_LATER`, `REJECT`, com comentários e possibilidade de desfazer antes de limpeza.
- Estado persistente no SQLite; progresso retomável entre sessões/dispositivos.
- UI responsiva e utilizável por toque em celular/tablet. Em TV, leitura/navegação quando navegador compatível; não prometer controle remoto universal.

### RF-06: Selects e CapCut

- Gerar MP4 a partir do original, jamais do proxy. Manter orientação correta e metadata relevante quando possível.
- `-c copy` é rápido mas limites dependem de keyframes; oferecer modo `fast` (pode não ser frame-exato) e `accurate` (recodifica com parâmetros explícitos). Mostrar diferença na UI.
- Verificar duração, decodificação básica, existência, tamanho e hash do output. Não apagar original antes da validação.
- Exportar manifesto CSV/JSON com take, origem, in/out, tags, orientação e nome de arquivo para CapCut. Não prometer importação automática de projeto CapCut.

### RF-07: Retenção, NAS e iCloud

- Dashboard de bytes brutos, mantidos, selects, proxies regeneráveis, candidatos a descarte e economia potencial/real.
- Política por decisão humana; prévia de operações com total de bytes, dependências e riscos. `REJECT` nunca executa delete automaticamente.
- Quarentena opcional no NAS com prazo configurável, seguida de purge somente com nova política/consentimento definido. Garantir que a quarentena não seja apresentada como economia física antes de purge.
- `KEEP_ORIGINAL` promove original e SRT associado. `KEEP_SELECT` preserva select validado e política explícita para SRT/telemetria. Guardar catálogo e histórico de descartados.
- iCloud: exportar para pasta configurável e informar `COPY_PENDING` / `COPIED_LOCAL`; **não declarar `SYNCED` sem verificação confiável**. Não acessar banco SQLite em pasta sincronizada.
- Cartão: somente aviso de liberação após ingestão verificada, nunca operação de delete/format.

## 8. API proposta (ajustar durante design)

| Método | Rota | Ação |
|---|---|---|
| GET/POST | `/api/trips` | listar/criar viagem |
| GET | `/api/sources` | listar fontes removíveis candidatas |
| POST | `/api/ingests` | criar ingestão confirmada |
| GET | `/api/jobs/{id}` | status/progresso/erros |
| GET | `/api/trips/{id}/media` | catálogo filtrado/paginado |
| GET | `/api/media/{id}` | metadata, tags, telemetria resumida |
| GET | `/api/assets/{id}/stream` | proxy/thumbnail com Range |
| POST | `/api/media/{id}/takes` | criar/editar limites (usar PATCH para editar) |
| POST | `/api/reviews` | registrar decisão humana |
| POST | `/api/exports` | enfileirar geração de selects |
| POST | `/api/retention/preview` | simular plano de limpeza |
| POST | `/api/retention/approve` | aprovar plano versionado e expirar aprovação |
| POST | `/api/retention/execute` | executar somente plano aprovado e revalidado |
| GET | `/api/reports/{trip_id}` | armazenamento, auditoria, exportações |

Requisitos de API: validação de entrada, paginação, autorização, rate limiting básico para login, proteção CSRF se sessão por cookie, tokens não em URL, mensagens de erro seguras, limites de request e URLs de mídia com IDs (não paths arbitrários).

## 9. Segurança e operação

- Configuração por `.env` fora do controle de versão; credenciais NAS no gerenciador de credenciais do Windows quando possível; nunca no manifesto.
- Bind na interface LAN configurada, firewall do Windows com regra restrita à sub-rede doméstica. Preferir `127.0.0.1` até configurar autenticação.
- Login para revisão e permissões adicionais para aprovar limpeza; senha com hash forte. Se apenas dois usuários, ainda registrar `actor`.
- CORS restrito; validar Origin/CSRF; `SameSite` e `HttpOnly` em cookies; TLS via reverse proxy local se necessário.
- Sanitizar nomes e paths; proteger contra symlink/reparse points, traversal e troca de caminho entre validação e operação; whitelists de raízes NAS.
- Jobs persistentes e observáveis; logs rotativos sem GPS detalhado ou credenciais por padrão. Backup consistente de SQLite e manifestos; testar restauração.
- Windows pode dormir/desligar: worker retoma jobs, UI indisponível enquanto host estiver desligado.
- Testar queda do NAS, reconexão SMB, perda de espaço, reinício no meio da cópia, mídia corrompida e ffmpeg travado.

## 10. Plano de execução incremental (Superpowers)

**Regra para cada tarefa:** teste falhando → implementação mínima → teste passando → revisão → commit pequeno. Registrar comandos e resultado. Não iniciar próxima fase sem checkpoint.

### Fase 0 — Fundação

1. Criar projeto Python, lint/type-check/testes, `.env.example`, configuração de paths Windows/UNC.
2. Implementar verificação de dependências ffmpeg/ffprobe e health check.
3. Criar esquema SQLite, migrações e teste de upgrade/rollback ou recuperação.
4. Implementar logs estruturados e job runner persistente mínimo.

**Aceite:** aplicação inicia localmente, cria banco local, reconhece NAS configurado, testes unitários passam; nenhuma escrita no SD.

### Fase 1 — Ingestão segura (MVP operacional)

1. Descoberta de fontes e inventário MP4/SRT, com fixture de cartão simulado.
2. Modelo de viagem e ingest job.
3. Cópia streaming com arquivo parcial e retomada segura.
4. SHA-256 origem/destino, manifestos e detecção de duplicidade.
5. CLI `scan`, `ingest --dry-run`, `ingest`, `verify`; progresso e relatório.
6. Testes de interrupção, falta de espaço, hash divergente e NAS offline.

**Aceite:** cópia validada sem tocar na origem; reinício idempotente; arquivo divergente nunca sobrescrito silenciosamente; aviso de liberação do cartão é condicionado à validação.

### Fase 2 — Catálogo DJI

1. Wrapper ffprobe com timeout e fixtures JSON.
2. Parser SRT robusto e associação de pares.
3. Orientação efetiva por display matrix, FPS racional, timestamps UTC/local.
4. Telemetria e estatísticas GPS com filtros e yaw unwrap.
5. API/CLI de catálogo e exportação CSV/JSON.

**Aceite:** amostras horizontais/verticais classificadas corretamente; SRT ausente não quebra pipeline; gimbal yaw não é tratado como heading.

### Fase 3 — Proxies e interface LAN (primeira entrega à esposa)

1. Gerador de proxy/thumbnail e worker.
2. FastAPI, autenticação, endpoints de mídia com Range.
3. Lista de viagens, grade de mídia, player responsivo.
4. Revisão manual, marcação in/out, persistência no SQLite.
5. Testes em Windows + navegador de PC e smartphone na LAN.

**Aceite:** esposa consegue assistir, marcar e salvar decisões sem acesso direto ao NAS; mídia vertical aparece corretamente; progresso persiste após reinício.

### Fase 4 — Movimento, POI e sugestões

1. Classificador de movimento com testes sintéticos (órbita vs pan estacionário vs travelling).
2. Agrupamento GPS e nomes manuais de POI; geocoding opcional posterior.
3. Métricas técnicas e candidatos a takes, com evidência/confiança e `UNKNOWN`.
4. Filtros de revisão e comparação de takes semelhantes.

**Aceite:** algoritmo não inventa precisão; tags corrigíveis; sugestões nunca acionam exclusão.

### Fase 5 — Selects e exportação

1. Planejador de exportação a partir de decisões humanas.
2. Corte `fast` e `accurate` com ffmpeg; nomes estáveis.
3. Validação de outputs e manifesto para CapCut.
4. Relatório de espaço e testes de cortes/rotação.

**Aceite:** selects vêm do original e reproduzem no navegador/editor; original permanece até validação; modos de corte têm limitações explicitadas.

### Fase 6 — Retenção e limpeza controlada

1. Simulador de retenção e verificação de dependências.
2. Aprovação explícita, versionada, com expiração e revalidação.
3. Promoção de KEEP, quarentena, purge opt-in e auditoria.
4. Exportação para pasta iCloud sem alegar sincronização concluída.
5. Testes de falha no meio da operação e recuperação.

**Aceite:** nenhum delete sem aprovação; relatório mostra economia real vs potencial; nunca exclui último exemplar necessário.

### Fase 7 — Robustez e distribuição

1. Empacotar execução Windows (script/serviço agendado, conforme escolha), documentação de setup NAS e firewall.
2. Backup/restore do SQLite e manifestos; monitor de saúde.
3. Teste de ponta a ponta com cartão simulado e viagem real pequena.
4. Testes de carga moderada, segurança de paths, recuperação de jobs e UX móvel.

**Aceite:** usuário consegue instalar, operar, recuperar e desinstalar sem perda de mídia; runbook reproduzível.

## 11. Matriz mínima de testes

| Cenário | Resultado esperado |
|---|---|
| Mesmo cartão importado duas vezes | sem duplicar mídia, relatório dos novos |
| MP4 sem SRT / SRT órfão | status explícito, sem crash |
| Vertical com rotação 90° | proxy e UI 9:16 |
| NAS desconecta durante cópia | job interrompido, parcial preservado, retomada segura |
| Hash destino diverge | `FAILED`, nunca `VERIFIED` |
| SD removido durante leitura | falha segura, sem dano ao catálogo |
| Falta de espaço | bloqueio preventivo ou falha recuperável |
| Dois browsers editam mesma decisão | controle de revisão/conflito |
| URL com `../` | acesso negado |
| Tentativa de delete sem aprovação | acesso negado e auditoria |
| Corte fast fora de keyframe | aviso/limitação registrada |
| Banco restaurado e NAS remapeado | caminhos relativos resolvem corretamente |

## 12. Entregáveis e definição de pronto

- Código fonte, testes, migrações, `.env.example`, README, guia de operação Windows/NAS.
- CLI de ingestão e API/UI de revisão; logs, manifestos, relatórios e backup.
- Documentação de decisões arquiteturais e limitações técnicas.
- Testes automatizados e checklist manual de ponta a ponta; resultado real de cada comando documentado.
- Nenhum dado fictício apresentado como extraído de vídeo real; dados de demonstração identificados como tais.
- Nenhuma exclusão física habilitada por padrão.

## 13. Perguntas não bloqueantes e parâmetros configuráveis

Definir por configuração ou durante a implementação, sem travar o MVP: caminho UNC e credenciais do NAS; capacidade/velocidade; pasta de staging (NAS vs SSD local); limite de concorrência; tamanho do proxy; retenção de quarentena; exigência de segunda cópia antes de liberar cartão; estratégia de backup do banco; usuário/senha inicial; IP/porta da LAN. **Não codificar valores específicos de ambiente.**

**Checkpoint para o Codex:** comece pela Fase 0 + plano detalhado da Fase 1. Não implemente o projeto inteiro em uma única execução.

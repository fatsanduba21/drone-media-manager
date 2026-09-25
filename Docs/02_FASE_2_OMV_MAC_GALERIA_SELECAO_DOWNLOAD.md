# Drone Media Manager — Fase 2: OMV → Mac → Catálogo → Galeria → Seleção → Download

**Base auditada:** `DIAGNOSTICO_FUNCIONAL_E_PRIORIDADES.md`  
**Commit auditado da base:** `1a1de0b3c26d420cdc4c954d0d3e8ccac7d11bd7`  
**Pré-condição:** Fase 1 concluída e aceita com mídia real no Windows → OMV.  
**Objetivo:** transformar o conteúdo editorial publicado no OMV em uma aplicação utilizável no Mac mini, permitindo navegar, visualizar, selecionar e baixar apenas os originais escolhidos.

---

## 1. Estado de partida

A Fase 1 entrega:

```text
WINDOWS
  source
    ↓
  inventário + MP4/SRT/JPG/JPEG
    ↓
  ffprobe + classificação
    ↓
  naming editorial
    ↓
  APPLY
    ↓
OMV
  <trip_slug>/
    <poi>/
      YOUTUBE_16x9/
      INSTAGRAM_9x16/
      FOTOS/
      OUTROS_REVISAR/
    MANIFESTO.json
```

O `MANIFESTO.json` real possui:

```text
schema_version = 1
trip.name
trip.slug
trip.external_id = null
assets[]
orphan_srt[]
unsupported[]
```

Cada asset pode conter:

```text
asset_id
source.*
video.*
classification
location.*
editorial.*
output.*
verification_status
```

O Mac ainda não possui importador, catálogo compatível com `asset_id`, thumbnails, proxies, galeria, seleção, downloads ou login de usuário final.

---

## 2. Princípio de arquitetura

A Fase 2 deve consumir o contrato criado pela Fase 1. Não reconstruir no Mac o fluxo editorial já executado no Windows.

```text
OMV
 ├── MANIFESTO.json
 ├── MP4
 ├── SRT
 └── JPG/JPEG
       │
       ▼
MAC MINI
  Importer
       ↓
  SQLite Catalog
       ↓
  Derivatives
       ↓
  API
       ↓
  Gallery
       ↓
  Selection
       ↓
  Download
```

### Regra central de paths

O Mac deve usar:

```text
DMM_OMV_ROOT + output.*_relative_path
```

Paths absolutos da origem Windows (`D:\...`, `P:\...`) são históricos e nunca devem ser usados para serving no Mac.

---

## 3. Persistência

### 3.1 Reutilizar `Trip`

A tabela `trips` existente deve ser reaproveitada.

Correlação:

```text
manifest.trip.slug
    ↓
Trip.slug
```

### 3.2 Não forçar o catálogo editorial dentro do `MediaFile` legado

O `MediaFile` atual depende do pipeline antigo, exige `ingest_item_id` e não comporta diretamente os metadados editoriais da Fase 1.

A Fase 2 deve introduzir um catálogo próprio.

---

## 4. Modelo conceitual recomendado

Os nomes podem variar conforme o estilo do projeto.

### CatalogAsset

```text
id                  UUID interno
asset_id            string única do Windows
trip_id             FK Trip

media_type          VIDEO | PHOTO
classification      YOUTUBE_16X9 | INSTAGRAM_9X16 | FOTOS | OUTROS_REVISAR

codec               nullable
duration_ms          nullable
fps                  nullable

encoded_width        nullable
encoded_height       nullable
display_width        nullable
display_height       nullable
rotation_degrees     nullable

capture_date         nullable
capture_date_source  nullable

poi_final            nullable
poi_suggested        nullable
movement             nullable
people               nullable

verification_status
created_at
updated_at
```

### AssetFile

```text
id
catalog_asset_id
role                ORIGINAL | SRT
rel_path
sha256
size_bytes           nullable inicialmente
availability_status
created_at
updated_at
```

### ManifestImport

```text
id
trip_id
manifest_rel_path
manifest_sha256
schema_version
status
imported_at
asset_count
error_count
```

---

## 5. Identidade e idempotência

### Trip

```text
slug inexistente
→ criar Trip

slug existente + nome compatível
→ reutilizar

slug existente + nome incompatível
→ CONFLICT
```

### Asset

```text
asset_id inexistente
→ INSERT

asset_id existente + hashes/paths compatíveis
→ ALREADY_IMPORTED / UPDATE não destrutivo

asset_id existente + hash incompatível
→ CONFLICT
```

### Mesmo conteúdo com outro `asset_id`

O `asset_id` da Fase 1 pode mudar se o mesmo conteúdo for recopiado em outro filesystem.

Detectar:

```text
mesmo trip
+ mesmo SHA-256 principal
+ asset_id diferente
```

Reportar como possível duplicado. Não fazer merge automático nesta fase.

---

## 6. Regra de paths no Mac

Configuração esperada:

```text
DMM_OMV_ROOT=/Volumes/...
```

Resolver:

```text
absolute_path = DMM_OMV_ROOT / relative_path
```

Validar:

- path permanece dentro da raiz autorizada;
- arquivo existe;
- tipo esperado;
- nenhuma traversal;
- nenhum path absoluto vindo do manifesto é usado diretamente.

---

# Fase 2A — Importação do manifesto e catálogo SQLite

**Prioridade:** P0

## Objetivo

Fazer o Mac:

1. localizar um `MANIFESTO.json` real no OMV;
2. validar schema;
3. criar/reutilizar `Trip`;
4. importar assets;
5. criar vínculos com arquivos físicos;
6. verificar disponibilidade;
7. repetir importação sem duplicar.

## Escopo

- migration(s) do catálogo;
- modelos ORM;
- repository/import service;
- leitura de `schema_version=1`;
- validação dos campos necessários;
- resolução segura de paths;
- criação/reuso de Trip;
- upsert por `asset_id`;
- importação de ORIGINAL/SRT;
- status de disponibilidade;
- auditoria `ManifestImport`;
- CLI/admin command;
- preview/dry-run;
- testes unitários;
- testes de integração SQLite;
- teste com manifesto real;
- teste com arquivos reais acessíveis no OMV;
- segunda importação idempotente;
- conflitos explícitos.

## Fora do escopo

- thumbnail;
- proxy;
- player;
- UI;
- login;
- seleção;
- download;
- parser GPS/SRT;
- edição de tags.

## Aceite

Com o manifesto real:

```text
1 Trip
14 CatalogAssets
18 AssetFiles
  5 MP4
  4 SRT
  9 JPG
```

Segunda importação:

```text
1 Trip
14 CatalogAssets
18 AssetFiles
0 duplicados
0 alterações destrutivas
```

Com Windows desligado, o Mac deve conseguir resolver os 18 arquivos via OMV.

---

# Fase 2B — Thumbnails e proxies

**Prioridade:** P1

## Objetivo

Criar derivados regeneráveis para navegação rápida.

## Armazenamento

Originais:

```text
OMV
```

Derivados:

```text
cache local no Mac
```

Configuração sugerida:

```text
DMM_DERIVATIVES_ROOT
```

## Thumbnail

Vídeo:

```text
MP4 original
→ ffmpeg
→ thumbnail
```

Foto:

```text
JPG/JPEG
→ thumbnail
```

## Proxy

Perfil inicial:

```text
H.264
yuv420p
720p
+faststart
AAC somente se houver áudio
```

Preservar proporção e orientação.

## Versionamento

```text
asset_id
source_sha256
profile_version
```

Exemplos:

```text
thumbnail_profile = grid-v1
proxy_profile = web-720p-v1
```

## Aceite

```text
5 vídeos -> 5 thumbnails + 5 proxies
9 fotos   -> 9 thumbnails
```

- originais intactos;
- segunda execução reutiliza derivados válidos;
- todos os proxies reproduzem no navegador;
- vídeos verticais aparecem verticais.

---

# Fase 2C — API e primeira galeria

**Prioridade:** P2

## Objetivo

Permitir navegação real da viagem no browser.

## API mínima

```text
GET /api/catalog/trips
GET /api/catalog/trips/{slug}
GET /api/catalog/trips/{slug}/assets
GET /api/catalog/assets/{asset_id}
GET /api/catalog/assets/{asset_id}/thumbnail
GET /api/catalog/assets/{asset_id}/proxy
```

Filtros:

```text
classification
poi
movement
people
media_type
```

## Serving

- acesso por `asset_id`;
- nunca aceitar path arbitrário;
- proxy com HTTP Range/seek;
- thumbnail com cache adequado.

## UI

MVP:

```text
Viagens
  ↓
Galeria
  ↓
Detalhe/player
```

Card mostra no mínimo:

- thumbnail;
- classificação;
- duração;
- POI;
- movimento;
- pessoas.

## Tecnologia

Aproveitar FastAPI existente. Não adicionar SPA complexa antes de provar necessidade.

## Aceite

A esposa consegue:

1. abrir a viagem;
2. ver 14 assets;
3. filtrar 9:16;
4. abrir vídeo;
5. fazer seek;
6. voltar à galeria.

---

# Fase 2D — Seleção persistente e download

**Prioridade:** P3

## Seleção

Persistir no SQLite.

Modelo conceitual:

```text
AssetSelection
  id
  catalog_asset_id
  user_id
  selected
  updated_at
```

Critério:

```text
selecionar
→ fechar navegador
→ reabrir
→ seleção continua
```

## Download individual

```text
GET /api/catalog/assets/{asset_id}/download
```

Sempre entrega o ORIGINAL do OMV, nunca proxy.

## Download em lote

```text
POST /api/catalog/trips/{slug}/download-selected
```

Gerar ZIP por streaming. Não carregar todos os vídeos em RAM.

## Naming

`Content-Disposition` usa o nome editorial da Fase 1.

## Autenticação

Neste ponto entra autenticação de usuário final.

Não reutilizar token de worker.

MVP:

```text
User
username
password_hash
```

+ sessão/cookie.

## Aceite

Selecionar três assets, fechar/reabrir e baixar apenas esses três em qualidade original.

---

# Fase 2E — Aceite end-to-end real

**Prioridade:** P4

## Ambiente

```text
Windows desligado
OMV ligado
Mac mini ligado
Mac da esposa na LAN
```

## Cenário

1. abrir aplicação;
2. autenticar;
3. abrir viagem;
4. ver 14 assets;
5. filtrar `INSTAGRAM_9X16`;
6. abrir proxy;
7. fazer seek;
8. selecionar três;
9. fechar browser;
10. reabrir;
11. seleção permanece;
12. baixar selecionados;
13. receber somente os três;
14. arquivos são originais do OMV;
15. filenames são editoriais.

## Critério final

A triagem pode ser feita sem acessar diretamente pasta bruta, Windows, acervo completo ou iCloud.

---

## 7. Fora da Fase 2

- parsing completo de GPS/SRT;
- reverse geocoding;
- sugestão automática de POI;
- classificação automática de movimento;
- visão computacional;
- edição de tags por asset;
- in/out;
- selects;
- scoring;
- CapCut;
- iCloud;
- retenção;
- purge.

---

## 8. Dívidas que não devem bloquear 2A

Não transformar a Fase 2A em refatoração geral.

Só corrigir se bloquear o importador:

- `MediaFile` legado;
- `IngestItem`;
- worker sem dispatch;
- pipeline antigo `00_INBOX_ORIGINALS`;
- falta de CRUD web de Trip;
- autenticação final;
- proxies;
- frontend.

---

## 9. Ordem recomendada

```text
2A Import Manifest + Catalog
      ↓ checkpoint
2B Derivatives
      ↓ checkpoint
2C API + Gallery
      ↓ checkpoint
2D Selection + Download
      ↓ checkpoint
2E E2E Acceptance
```

Não executar a Fase 2 inteira em um único prompt.

---

## 10. Definition of Done da Fase 2

A Fase 2 termina somente quando, com Windows desligado:

- Mac lê catálogo importado;
- viagem aparece;
- thumbnails aparecem;
- vídeos reproduzem via proxy;
- filtros funcionam;
- seleção persiste;
- download entrega originais;
- download em lote contém somente selecionados;
- nomes editoriais da Fase 1 são preservados.

# Prompt para o Codex — Implementar somente a Fase 2A

Leia antes de alterar código:

```text
Docs/DIAGNOSTICO_FUNCIONAL_E_PRIORIDADES.md
Docs/02_FASE_2_OMV_MAC_GALERIA_SELECAO_DOWNLOAD.md
```

Também inspecione o manifesto real da Fase 1 e o registro de aceite existente no repositório.

---

## Objetivo desta execução

Implementar **somente a Fase 2A**:

> importar o `MANIFESTO.json` produzido pela Fase 1 no OMV para um catálogo editorial persistido no SQLite do Mac, correlacionando Trip e assets, resolvendo os arquivos físicos no OMV e garantindo idempotência.

Não implementar thumbnails, proxies, galeria, UI, seleção ou download nesta execução.

---

## Estado real que deve ser respeitado

A Fase 1 já produz um manifesto `schema_version=1`.

Ele contém:

```text
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

O manifesto real de aceite possui:

```text
14 assets
18 arquivos físicos
  5 MP4
  4 SRT
  9 JPG
```

A segunda execução da Fase 1 foi idempotente.

---

## Regra de arquitetura

A importação deve ser:

```text
OMV MANIFEST
     ↓
Importer
     ↓
Trip + CatalogAsset + AssetFile
     ↓
SQLite
```

Não reexecutar classificação no Mac.

Não rodar ffprobe no importador para recriar informação já presente no manifesto.

Não usar paths absolutos da origem Windows.

---

## Paths

O Mac deve resolver mídia usando:

```text
DMM_OMV_ROOT
+
output.video_relative_path
output.photo_relative_path
output.srt_relative_path
```

Nunca usar:

```text
source.video_path
source.photo_path
source.srt_path
```

para abrir arquivos no Mac.

Esses campos são apenas históricos.

Todos os paths resolvidos devem permanecer dentro da raiz autorizada.

Testar path traversal.

---

## Trip

Reutilize a tabela `Trip` existente.

Política:

```text
manifest.trip.slug inexistente
→ criar Trip

slug existente + nome compatível
→ reutilizar Trip

slug existente + nome incompatível
→ CONFLICT
```

Não inventar `trip_id` no manifesto.

O `trip_id` é interno do SQLite e nasce/é resolvido no importador.

Defina claramente como `nas_rel_path` será preenchido para uma viagem importada do manifesto.

Não reutilize o contrato legado `trips/<slug>/00_INBOX_ORIGINALS` se ele não corresponde à Fase 1.

---

## Catálogo editorial

Não force os assets da Fase 1 para dentro de `MediaFile` se isso exigir criar `IngestItem` fictício.

O `MediaFile` atual pertence ao pipeline legado e exige `ingest_item_id`.

Implemente um modelo editorial separado, com nomes coerentes com o projeto.

Modelo conceitual:

### CatalogAsset

```text
id
asset_id UNIQUE
trip_id FK

media_type
classification

codec nullable
duration_ms nullable
fps nullable

encoded_width nullable
encoded_height nullable
display_width nullable
display_height nullable
rotation_degrees nullable

capture_date nullable
capture_date_source nullable

poi_final nullable
poi_suggested nullable
movement nullable
people nullable

verification_status

created_at
updated_at
```

### AssetFile

```text
id
catalog_asset_id FK
role ORIGINAL | SRT
rel_path
sha256
size_bytes nullable
availability_status
created_at
updated_at
```

Ajuste o schema se o estilo do projeto exigir, mas preserve essas responsabilidades.

---

## Auditoria da importação

Crie persistência equivalente a:

```text
ManifestImport
```

com no mínimo:

```text
id
trip_id
manifest_rel_path
manifest_sha256
schema_version
status
asset_count
error_count
imported_at
```

Isso deve permitir saber:

- qual manifesto foi importado;
- quando;
- qual schema;
- resultado;
- quantidade de assets.

---

## Identidade e idempotência

### Asset

Use:

```text
manifest.asset_id
```

como chave externa única do catálogo.

#### Primeira importação

```text
asset_id inexistente
→ INSERT
```

#### Segunda importação

```text
asset_id existente
+ hashes/paths compatíveis
→ ALREADY_IMPORTED ou UPDATE não destrutivo
```

Não duplicar.

#### Conflito

```text
asset_id existente
+ hash principal incompatível
→ CONFLICT
```

Não sobrescrever silenciosamente.

---

## Mesmo conteúdo com outro `asset_id`

A Fase 1 calcula `asset_id` usando identidade da origem + SHA-256.

O mesmo conteúdo recopiado em outro filesystem pode ganhar outro `asset_id`.

Se detectar:

```text
mesmo trip
+ mesmo SHA-256 principal
+ asset_id diferente
```

registre/report como possível duplicado.

Não faça merge automático nesta fase.

---

## Sidecar SRT

Para asset de vídeo:

- ORIGINAL MP4 vira um `AssetFile`;
- SRT pareado vira outro `AssetFile` role `SRT`;
- vídeo sem SRT é válido;
- `srt_status=missing` não é erro;
- hash SRT deve ser persistido;
- não parsear GPS nesta fase.

Foto:

- somente `AssetFile ORIGINAL`;
- sem SRT.

---

## Validação do manifesto

Aceitar somente schema suportado.

Inicialmente:

```text
schema_version == 1
```

Para versão diferente:

```text
UNSUPPORTED_SCHEMA
```

sem importação parcial silenciosa.

Validar pelo menos:

- trip;
- slug;
- asset_id;
- classification;
- verification_status;
- output path principal;
- sha256 principal;
- coerência VIDEO/PHOTO;
- SRT path/hash quando presente.

Assets com `verification_status != VERIFIED` não devem ser tratados como disponíveis normalmente.

Defina o comportamento explicitamente e teste.

---

## Disponibilidade física

No import:

```text
relative_path
→ resolve dentro de DMM_OMV_ROOT
→ arquivo existe?
```

Persistir um estado equivalente a:

```text
AVAILABLE
MISSING
```

Nesta fase não precisa falhar toda a importação se um asset estiver ausente, desde que:

- o problema seja registrado;
- o asset não seja apresentado como disponível;
- o resumo da importação indique erro/indisponibilidade.

Se o projeto preferir política mais estrita, documente e teste.

---

## Hash

Não é necessário recalcular todos os hashes em toda importação se isso tornar o processo caro.

Mas:

- persistir os hashes declarados pelo manifesto;
- permitir opção/modo de verificação física;
- no aceite real da 2A, verificar pelo menos que os 18 arquivos existem;
- preferencialmente validar hash de uma amostra ou do conjunto se o custo for aceitável.

Não assumir que `VERIFIED` no manifesto significa que o Mac abriu o arquivo.

---

## CLI/admin command

Implemente uma interface operacional simples.

Exemplo conceitual:

```powershell
dmm-server catalog import-manifest <manifest>
```

ou:

```powershell
dmm-catalog import <manifest>
```

Escolha o padrão mais coerente com o projeto.

Precisa suportar:

```text
PREVIEW / DRY-RUN
IMPORT
```

O preview deve mostrar pelo menos:

```text
Trip
schema_version
assets encontrados
novos
já importados
conflitos
arquivos disponíveis
arquivos ausentes
```

---

## Migrações

Criar migration Alembic adequada.

Garantir:

- upgrade;
- schema esperado;
- constraints;
- unique indexes;
- foreign keys;
- rollback se o projeto mantém suporte real a downgrade.

Não editar migrations antigas já aplicadas.

---

## Testes obrigatórios

### Unitários

Cobrir:

- schema_version=1;
- schema não suportado;
- resolução segura de path;
- traversal;
- mapeamento de video asset;
- mapeamento de photo asset;
- SRT paired;
- SRT missing;
- classificação;
- metadata nullable.

### Integração SQLite

Cobrir:

#### Primeira importação

```text
1 Trip
N assets
arquivos associados
```

#### Segunda importação

```text
sem duplicação
```

#### Conflict de Trip

Mesmo slug + nome incompatível.

#### Conflict de asset

Mesmo `asset_id` + SHA-256 diferente.

#### Possível duplicado

Mesmo hash + `asset_id` diferente.

#### Arquivo ausente

Persistir/reportar indisponibilidade corretamente.

---

## Aceite com o manifesto real da Fase 1

Use o manifesto real produzido no aceite da Fase 1.

Não substitua o aceite por fixture sintética.

Antes de executar contra uma base real, use banco de teste/staging se necessário.

O resultado esperado deve corresponder ao artefato auditado:

```text
Trip: 1

CatalogAssets: 14

AssetFiles: 18
  MP4 ORIGINAL: 5
  SRT: 4
  JPG ORIGINAL: 9
```

Validar:

- dois assets `INSTAGRAM_9X16` por rotação estão presentes;
- três vídeos horizontais estão presentes;
- quatro vídeos têm SRT;
- um vídeo não tem SRT;
- nove fotos estão presentes.

---

## Idempotência real

Importar o mesmo manifesto novamente.

Resultado obrigatório:

```text
Trip: continua 1
CatalogAssets: continua 14
AssetFiles: continua 18

created assets: 0
created files: 0
conflicts: 0
duplicates: 0
```

A auditoria de `ManifestImport` pode registrar uma nova tentativa/import event, mas o catálogo não pode duplicar.

---

## Teste do handoff real no Mac

Se esta execução estiver rodando no Windows e não puder validar o Mac real, não finja que validou.

Nesse caso:

1. implemente e teste tudo que for possível;
2. escreva um runbook/checklist exato para executar no Mac;
3. deixe o aceite "Mac real" explicitamente pendente.

Se estiver no Mac com o OMV montado:

1. configure `DMM_OMV_ROOT`;
2. importe o manifesto real;
3. valide os 18 paths;
4. desligue o Windows ou confirme que ele não é utilizado;
5. rode novamente a consulta de disponibilidade.

Objetivo:

```text
Mac + OMV
funcionam sem Windows
```

---

## Não implementar nesta execução

Pare se perceber que está começando a implementar:

- thumbnails;
- proxies;
- ffmpeg derivatives;
- HTTP Range;
- frontend;
- galeria;
- autenticação de usuário final;
- seleção;
- download;
- ZIP;
- SRT GPS;
- geocoding;
- movimento automático.

Esses itens pertencem às próximas subfases.

---

## Não quebrar o legado

A suite existente deve continuar passando.

Não remova:

- MediaFile;
- IngestItem;
- worker;
- snapshots;
- pipeline antigo;

apenas porque o novo catálogo não os utiliza.

Evite migração destrutiva.

---

## Gates de qualidade

Execute no mínimo:

```text
pytest da 2A
suite geral
ruff check
mypy src
migration test
```

Se `ruff format --check .` continuar falhando apenas pela dívida já documentada, não reformate o repositório inteiro nesta tarefa.

Registre isso como limitação existente.

---

## Documentação

Ao finalizar:

1. atualize documento de progresso/checkpoint da Fase 2A;
2. documente comandos reais;
3. documente migrations/modelos criados;
4. documente resultados do manifesto real;
5. documente o que ficou pendente no Mac real, se aplicável;
6. não marque Fase 2B como iniciada.

---

## Critério de encerramento

A Fase 2A termina somente quando estiver comprovado que:

- manifesto schema 1 é validado;
- Trip é criado/reutilizado;
- `asset_id` é persistido;
- 14 assets reais entram no catálogo;
- 18 arquivos reais são representados;
- MP4/SRT permanecem associados;
- paths são resolvidos pelo OMV, não pela origem Windows;
- segunda importação não duplica;
- conflitos são detectados;
- arquivos ausentes são explícitos;
- suite relevante passa.

Então **pare**.

Próxima fase:

> Fase 2B — thumbnails e proxies.

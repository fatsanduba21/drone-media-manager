# Fase 1 v2 — Hoje: Windows → OMV, classificação + naming

**Objetivo:** terminar o dia com classificação + naming funcionando ponta a ponta no Windows e com a saída salva no OMV.  
**Mac/SQLite:** fora do caminho crítico desta fase.

---

# 1. Contrato do fluxo

```text
SOURCE NO WINDOWS
      ↓
scan
      ↓
MP4 + SRT pairing
      ↓
ffprobe
      ↓
classificação
      ↓
POI/tags
      ↓
naming
      ↓
PLAN
      ↓
APPLY
      ↓
OMV
      ↓
MANIFESTO.json
```

O Mac entra somente na fase seguinte.

---

# 2. Viagem sem `trip_id`

Não consultar o SQLite do Mac.

Usar:

```json
{
  "trip": {
    "name": "Fernando de Noronha",
    "slug": "fernando-de-noronha",
    "external_id": null
  }
}
```

Depois, no Mac:

```text
trip.slug/external_id
      ↓
localiza/cria Trip
      ↓
trip_id interno
```

`trip_id` nunca entra no filename.

---

# 3. MP4 + SRT = um asset lógico

Para o DJI Flip deste projeto:

```text
DJI_0032.MP4
DJI_0032.SRT
```

deve ser tratado como um único asset.

Regras:

- mesmo basename;
- extensão case-insensitive;
- vídeo sem SRT continua válido;
- SRT órfão é reportado;
- SRT não é apagado;
- SRT não é renomeado isoladamente;
- no OMV, MP4 e SRT recebem o mesmo basename editorial;
- manifesto registra a relação.

Exemplo:

```text
2026-09-14_baia-dos-porcos_orbita_pessoas-sim_16x9_a1b2c3d4.mp4
2026-09-14_baia-dos-porcos_orbita_pessoas-sim_16x9_a1b2c3d4.srt
```

---

# 4. Responsabilidade das ferramentas

## ffprobe — obrigatório

Usar para:

- codec;
- duração;
- FPS;
- width/height;
- rotation;
- display matrix;
- dimensão efetiva.

## ExifTool — complementar

Pode ajudar em:

- datas;
- metadata auxiliar;
- GPS embutido em outros modelos.

Não depender de GPS do MP4 no DJI Flip.

## SRT

Hoje:

- parear;
- preservar;
- opcionalmente extrair GPS.

Classificação semântica completa de telemetria fica para depois.

## Reverse geocoding

Não bloqueia a entrega.

Se implementado:

```text
SRT GPS -> poi_suggested
```

Nunca:

```text
SRT GPS -> poi_final automático
```

---

# 5. Classificação

Categorias:

```text
YOUTUBE_16X9
INSTAGRAM_9X16
FOTOS
OUTROS_REVISAR
```

Usar dimensão de exibição após rotação/display matrix.

Casos obrigatórios:

```text
3840x2160                    -> YOUTUBE_16X9
1920x1080                    -> YOUTUBE_16X9
2160x3840                    -> INSTAGRAM_9X16
3840x2160 + rotation 90      -> INSTAGRAM_9X16
1920x1440                    -> OUTROS_REVISAR
1440x1920                    -> OUTROS_REVISAR
1080x1080                    -> OUTROS_REVISAR
JPG/JPEG                     -> FOTOS
```

Sem crop.

---

# 6. Naming

## Vídeo

```text
{data}_{poi}_{movimento}_pessoas-{pessoas}_{formato}_{id8}.mp4
```

## SRT

Mesmo basename do vídeo:

```text
{data}_{poi}_{movimento}_pessoas-{pessoas}_{formato}_{id8}.srt
```

## Foto

```text
{data}_{poi}_foto_{id8}.{ext}
```

## Regras

- lowercase;
- espaços → `-`;
- sanitizar caracteres Windows;
- evitar nomes reservados;
- determinístico;
- sem colisões;
- ID não depende do nome;
- nome não é banco de dados.

---

# 7. `asset_id`

O `asset_id`:

- nasce no fluxo Windows;
- fica no manifesto;
- não depende do `trip_id`;
- não muda quando o nome editorial muda;
- é reutilizado no Mac.

Preferência:

1. reaproveitar identidade estável já existente;
2. persistir no plano/manifesto;
3. registrar SHA-256 real durante cópia/verificação;
4. não chamar fingerprint de inventário de hash completo.

---

# 8. Regra de data

Preferência:

1. data fornecida pelo usuário;
2. data de captura confiável;
3. `desconhecido`.

Não usar `mtime` silenciosamente como data de gravação.

Se houver fallback:

```text
capture_date_source = filesystem_mtime
```

---

# 9. Manifesto mínimo

Exemplo:

```json
{
  "asset_id": "a1b2c3d4...",
  "trip": {
    "name": "Fernando de Noronha",
    "slug": "fernando-de-noronha"
  },
  "source": {
    "video_name": "DJI_0012.MP4",
    "video_path": "D:\\Drone\\FernandoNoronha\\DJI_0012.MP4",
    "sidecars": {
      "srt": {
        "status": "paired",
        "source_name": "DJI_0012.SRT",
        "source_path": "D:\\Drone\\FernandoNoronha\\DJI_0012.SRT"
      }
    }
  },
  "video": {
    "codec": "h264",
    "duration_ms": 18340,
    "fps": 29.97,
    "encoded_width": 3840,
    "encoded_height": 2160,
    "rotation_degrees": 0,
    "display_width": 3840,
    "display_height": 2160
  },
  "location": {
    "gps_source": "srt",
    "latitude": null,
    "longitude": null,
    "poi_suggested": null,
    "poi_final": "baia-dos-porcos"
  },
  "classification": "YOUTUBE_16X9",
  "editorial": {
    "movement": "orbita",
    "people": "desconhecido",
    "capture_date": "2026-09-14",
    "capture_date_source": "user"
  },
  "output": {
    "video_relative_path": "...mp4",
    "srt_relative_path": "...srt",
    "sha256": null
  }
}
```

---

# 10. Sequência de implementação

## Task 1 — Handoff

Formalizar:

```text
Windows -> OMV -> Manifesto -> Mac
```

Gate:

- nenhuma função desta fase precisa abrir SQLite do Mac.

## Task 2 — Classificador puro

Testar os casos da seção 5.

## Task 3 — ffprobe real

Extrair metadata audiovisual e respeitar display matrix/rotation.

Teste real:

- horizontal;
- vertical codificado vertical;
- horizontal + rotation 90.

## Task 4 — Inventário e sidecars

Incluir:

```text
.mp4
.srt
.jpg
.jpeg
```

Estados:

```text
VIDEO_WITH_SRT
VIDEO_WITHOUT_SRT
ORPHAN_SRT
PHOTO
UNSUPPORTED
```

## Task 5 — Manifesto preview

Gerar dados estruturados suficientes para reconstruir naming sem reprovar mídia.

## Task 6 — Tags manuais

CLI equivalente a:

```text
--trip
--poi
--movement
--people
--date
```

Defaults:

```text
movement = desconhecido
people = desconhecido
date = desconhecido
```

POI manual é suficiente para hoje.

## Task 7 — GPS do SRT (stretch)

Somente se Tasks 1–6 estiverem sólidas.

- extrair GPS;
- `gps_source = srt`;
- opcional reverse geocode;
- salvar em `poi_suggested`;
- nunca sobrescrever `poi_final`;
- erro de rede não interrompe lote.

## Task 8 — Naming

Gerar basename único e conjunto:

```text
basename.mp4
basename.srt
```

## Task 9 — PLAN

Não grava mídia.

Mostra:

- pareamento;
- classificação;
- problemas;
- nome final;
- destino;
- preview do manifesto.

## Task 10 — APPLY para OMV

- criar diretórios;
- copiar MP4;
- copiar SRT pareado;
- copiar fotos;
- não alterar origem;
- temporário → verificação → promoção;
- não sobrescrever divergentes;
- gravar `MANIFESTO.json` atomicamente.

Reutilizar motor de cópia existente se não trouxer dependências desnecessárias.

## Task 11 — Idempotência

Esperado:

```text
1ª execução:
  CREATED: N

2ª execução:
  ALREADY_OK: N
  CREATED: 0
  CONFLICT: 0
```

## Task 12 — Aceite real

Obrigatório:

- MP4 horizontal;
- MP4 vertical por rotação;
- MP4 + SRT do Flip;
- MP4 sem SRT;
- JPG/JPEG.

Desejável:

- SRT órfão;
- 4:3;
- arquivo não suportado.

Executar:

```text
PLAN
APPLY
PLAN
APPLY
```

Validar saída real no OMV.

---

# 11. Não fazer hoje

Não gastar o ciclo com:

- Mac;
- SQLite;
- `trip_id`;
- UI;
- login;
- worker distribuído;
- proxy;
- thumbnail;
- geocoding obrigatório;
- parser SRT completo;
- movimento automático;
- visão computacional;
- CapCut;
- iCloud;
- retenção.

---

# 12. Critério de parada

Pronto quando:

- [ ] source local funciona;
- [ ] SQLite/Mac não são necessários;
- [ ] MP4/SRT/JPG/JPEG são inventariados;
- [ ] MP4+SRT formam um asset;
- [ ] SRT órfão é reportado;
- [ ] ffprobe real funciona;
- [ ] rotação é respeitada;
- [ ] 16:9/9:16 corretos;
- [ ] outros → `OUTROS_REVISAR`;
- [ ] fotos → `FOTOS`;
- [ ] POI manual funciona;
- [ ] naming determinístico;
- [ ] MP4/SRT compartilham basename;
- [ ] PLAN mostra tudo antes da escrita;
- [ ] APPLY copia para OMV;
- [ ] origem fica intacta;
- [ ] manifesto contém vínculos e metadados;
- [ ] divergente não é sobrescrito;
- [ ] segunda execução é idempotente;
- [ ] mídia real passa ponta a ponta.

Quando cumprir isso, parar.

**Próxima fase:** OMV → Mac → SQLite → galeria → seleção → download.

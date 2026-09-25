# Prompt para o Codex — Fase 1 v2: Windows → OMV

Leia:

```text
Docs/DIAGNOSTICO_FUNCIONAL_E_PRIORIDADES.md
Docs/00_ROADMAP_PRIORIZADO_v2.md
Docs/01_FASE_1_HOJE_CLASSIFICACAO_E_NAMING_v2.md
```

## Contexto confirmado

A Fase 1 acontece inteiramente no Windows e termina no OMV.

```text
WINDOWS
source
  ↓
inventário + MP4/SRT
  ↓
ffprobe
  ↓
classificação
  ↓
POI/tags
  ↓
naming
  ↓
PLAN/APPLY
  ↓
OMV + MANIFESTO.json
```

Mac/SQLite entram apenas na fase seguinte:

```text
OMV manifest
  ↓
Mac
  ↓
localiza/cria Trip
  ↓
trip_id interno
  ↓
UI/seleção/download
```

**Não faça esta fase depender do SQLite ou do `trip_id` do Mac.**

---

## DJI Flip / SRT

No material real do projeto, o DJI Flip não traz latitude/longitude úteis no MP4.

Portanto:

- MP4 + SRT de mesmo basename = um asset lógico;
- preservar SRT;
- não apagar após naming;
- não renomear isoladamente;
- vídeo sem SRT continua válido;
- SRT órfão deve aparecer no relatório;
- MP4/SRT devem chegar ao OMV com o mesmo basename editorial;
- manifesto registra o vínculo.

GPS/reverse geocoding não bloqueia hoje.

Se implementado:

```text
SRT GPS -> poi_suggested
```

POI manual continua suficiente para o aceite e `poi_final` nunca é substituído automaticamente.

---

## Objetivo

Entregar:

> pasta real no Windows → análise → classificação → naming → cópia verificada para OMV → manifesto.

Prioridade:

**classificação + naming + preservação SRT + OMV + manifesto.**

---

## Restrições

1. Reaproveite a fundação.
2. Não reescreva a arquitetura.
3. Origem é somente leitura.
4. Não implementar Mac/UI/SQLite/trip_id.
5. Nenhum crop.
6. Não usar apenas `width > height`.
7. Considerar rotation/display matrix.
8. Horizontal não significa sempre 16:9.
9. Sem informação -> `desconhecido`.
10. Nome é projeção; manifesto guarda dados.
11. Não sobrescrever divergente.
12. Reexecução idempotente.
13. Usar mídia real no aceite.
14. Destino deve aceitar raiz UNC/mapeada do OMV.
15. MP4/SRT ficam vinculados do início ao fim.

---

## PLAN

Recebe algo equivalente a:

```text
source
trip
poi
output_omv
movement opcional
people opcional
date opcional
```

Produz:

- inventário;
- pareamento MP4/SRT;
- SRT órfãos/ausentes;
- ffprobe;
- classificação;
- preview dos nomes;
- preview dos destinos;
- preview do manifesto;
- erros/ignorados;
- nenhuma escrita de mídia.

---

## APPLY

- cria pastas no OMV;
- copia vídeos;
- copia SRT pareados com mesmo basename;
- copia fotos;
- não altera origem;
- temporário -> verificar -> promover;
- não sobrescreve divergentes;
- gera `MANIFESTO.json`;
- segunda execução não duplica.

---

## Classificação

```text
YOUTUBE_16X9
INSTAGRAM_9X16
FOTOS
OUTROS_REVISAR
```

Casos obrigatórios:

```text
3840x2160               -> YOUTUBE_16X9
2160x3840               -> INSTAGRAM_9X16
3840x2160 + rotation 90 -> INSTAGRAM_9X16
1920x1440               -> OUTROS_REVISAR
1080x1080               -> OUTROS_REVISAR
JPG/JPEG                -> FOTOS
```

---

## Ferramentas

### ffprobe — obrigatório

Extrair:

- codec;
- duração;
- FPS;
- width/height;
- rotation/display matrix.

### ExifTool — complementar

Pode auxiliar em datas/metadata. Não dependa de GPS no MP4 do Flip.

### SRT

Hoje:

- parear;
- preservar;
- opcionalmente extrair GPS.

Parser semântico completo fica para depois.

---

## Naming

Vídeo:

```text
{data}_{poi}_{movimento}_pessoas-{pessoas}_{formato}_{id8}.mp4
```

SRT:

```text
{data}_{poi}_{movimento}_pessoas-{pessoas}_{formato}_{id8}.srt
```

Foto:

```text
{data}_{poi}_foto_{id8}.{ext}
```

Regras:

- determinístico;
- sanitizado para Windows;
- ID estável;
- sem colisões;
- data com fonte registrada;
- não usar mtime silenciosamente;
- MP4/SRT compartilham basename.

---

## Manifesto

Registrar no mínimo:

```text
asset_id
trip.name
trip.slug
source video
source SRT/status
metadata ffprobe
classification
gps_source, se houver
poi_suggested, se houver
poi_final
movement
people
capture_date + source
destino MP4
destino SRT
hash/status de verificação
```

O manifesto é o contrato da futura importação no Mac.

---

## Ordem

Use ciclos pequenos:

```text
teste falhando
-> implementação mínima
-> teste passando
-> revisão
-> commit pequeno
```

Ordem:

1. formalizar Windows → OMV → Mac e remover dependência de trip_id;
2. classificador puro;
3. ffprobe;
4. rotation/display dimension;
5. fotos;
6. MP4/SRT pairing;
7. manifesto;
8. tags manuais;
9. naming conjunto;
10. PLAN;
11. APPLY no OMV;
12. idempotência;
13. aceite real.

GPS/reverse geocoding é stretch.

---

## Aceite real obrigatório

Usar:

- horizontal;
- vertical por rotação;
- MP4 + SRT real do DJI Flip;
- MP4 sem SRT;
- JPG/JPEG.

Depois:

```text
PLAN
APPLY
PLAN novamente
APPLY novamente
```

Validar fisicamente no OMV.

Reportar:

- comandos;
- arquivos;
- pareamentos;
- classificação;
- nomes;
- destinos;
- status 1ª execução;
- status 2ª execução;
- testes;
- limitações.

---

## Encerramento

Quando Windows → OMV estiver funcionando com:

- classificação;
- naming;
- SRT preservado;
- manifesto;
- origem intacta;
- idempotência;
- mídia real;

**pare.**

Não comece Mac/SQLite/UI nesta execução.

Próxima fase:

> OMV → Mac: importar manifesto, resolver Trip/trip_id no SQLite, gerar galeria, seleção persistente e download.

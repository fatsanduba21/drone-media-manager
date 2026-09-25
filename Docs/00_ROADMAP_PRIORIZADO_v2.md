# Drone Media Manager — Roadmap Priorizado v2

**Revisão:** 22/09/2026  
**Mudança principal:** Fase 1 acontece inteiramente no Windows e termina no OMV. O Mac/SQLite entra somente depois.

---

## 1. Arquitetura operacional confirmada

```text
WINDOWS
  origem local / pen drive / HD / pasta
          ↓
  inventário + pareamento MP4/SRT
          ↓
  ffprobe + classificação técnica
          ↓
  POI/tags manuais
          ↓
  naming editorial
          ↓
  PLAN / APPLY
          ↓
  cópia verificada para OMV
          ↓
  MANIFESTO.json
          │
────────── HANDOFF ──────────
          │
          ↓
MAC MINI
  importa manifesto
          ↓
  cria/localiza Trip no SQLite
          ↓
  associa asset_id ao trip_id interno
          ↓
  thumbnails/proxies/UI
          ↓
  seleção persistente
          ↓
  download dos originais escolhidos
```

### Decisões

- Windows fecha a Fase 1 ponta a ponta.
- OMV é o destino final da Fase 1.
- Mac mini não participa de classificação/naming.
- SQLite continua no Mac.
- `trip_id` do SQLite **não é dependência** do Windows.
- Windows trabalha com `trip_name`, `trip_slug` e, se necessário, `trip_external_id`.
- `MANIFESTO.json` é o contrato de handoff Windows → Mac.
- `asset_id` nasce antes do Mac e é preservado no manifesto.
- O nome editorial é derivado dos dados; não é a fonte de verdade.

---

# Fase 1 — Windows → OMV: classificação + naming + manifesto

**Prioridade:** P0  
**Meta:** funcionar hoje.

## Escopo

- aceitar pasta local, unidade removível, caminho mapeado ou UNC;
- aceitar material já copiado do cartão;
- não depender de SD recém-conectado;
- inventariar `.mp4`, `.srt`, `.jpg`, `.jpeg`;
- reportar formatos adicionais;
- tratar `MP4 + SRT` de mesmo basename como **um asset lógico**;
- permitir vídeo sem SRT;
- reportar SRT órfão;
- preservar SRT até o OMV;
- executar `ffprobe` real;
- registrar codec, duração, FPS, dimensões, rotação/display matrix e dimensões efetivas;
- classificar:
  - `YOUTUBE_16X9`;
  - `INSTAGRAM_9X16`;
  - `FOTOS`;
  - `OUTROS_REVISAR`;
- receber manualmente:
  - POI;
  - movimento;
  - pessoas;
  - data, quando necessário;
- gerar naming determinístico;
- usar o mesmo basename editorial para MP4 e SRT pareados;
- fazer preview antes da escrita;
- copiar/verificar para OMV;
- gerar `MANIFESTO.json`;
- preservar origem;
- ser idempotente.

## DJI Flip / sidecar SRT

No material real do DJI Flip usado no projeto, latitude/longitude não estão no MP4. Portanto:

- SRT é sidecar de primeira classe;
- não apagar depois do naming;
- não renomear isoladamente;
- copiar junto com o MP4;
- registrar a relação no manifesto;
- guardar para futura análise de GPS/telemetria.

### GPS / POI

Para hoje:

1. parear e preservar SRT — obrigatório;
2. POI manual — obrigatório e suficiente;
3. extrair GPS do SRT — desejável;
4. reverse geocoding — bônus.

Se reverse geocoding existir, gera apenas `poi_suggested`. O `poi_final` continua humano/corrigível.

## Não bloquear Fase 1 por

- Mac;
- SQLite;
- `trip_id`;
- UI;
- worker distribuído completo;
- thumbnails/proxies;
- geocoding obrigatório;
- classificação automática de movimento;
- visão computacional;
- CapCut/iCloud/retenção.

## Estrutura de saída

```text
<OMV_ROOT>/
  <TRIP>/
    <POI>/
      YOUTUBE_16x9/
      INSTAGRAM_9x16/
      FOTOS/
      OUTROS_REVISAR/
    MANIFESTO.json
```

Exemplo:

```text
FERNANDO-DE-NORONHA/
  BAIA-DOS-PORCOS/
    YOUTUBE_16x9/
      2026-09-14_baia-dos-porcos_orbita_pessoas-sim_16x9_a1b2c3d4.mp4
      2026-09-14_baia-dos-porcos_orbita_pessoas-sim_16x9_a1b2c3d4.srt
    INSTAGRAM_9x16/
      2026-09-14_baia-dos-porcos_aproximacao_pessoas-nao_9x16_e5f6a7b8.mp4
      2026-09-14_baia-dos-porcos_aproximacao_pessoas-nao_9x16_e5f6a7b8.srt
    FOTOS/
      2026-09-14_baia-dos-porcos_foto_91ac1f20.jpg
  MANIFESTO.json
```

## Aceite

A amostra real deve conter:

- horizontal;
- vertical por rotação;
- MP4 + SRT real;
- MP4 sem SRT;
- JPG/JPEG.

Ao final:

- classificação correta;
- 4:3/quadrado → `OUTROS_REVISAR`;
- nenhum crop;
- MP4/SRT vinculados;
- mesmo basename para o par no OMV;
- naming útil;
- POI manual disponível;
- manifesto completo;
- nenhum `trip_id` do Mac necessário;
- origem intacta;
- saída no OMV;
- segunda execução sem duplicação;
- conflitos sem sobrescrita.

---

# Fase 2 — OMV → Mac: catálogo + galeria + seleção + download

**Prioridade:** P1

## Handoff

```text
MANIFESTO.json
      ↓
trip_slug / trip_external_id
      ↓
localiza ou cria Trip
      ↓
trip_id interno
      ↓
upsert dos assets por asset_id
```

## Escopo

- importador idempotente do manifesto;
- mapear identidade externa da viagem → `trip_id`;
- upsert por `asset_id`;
- manter referência a MP4/SRT no OMV;
- thumbnails;
- proxies;
- API/UI;
- filtros;
- player/fotos;
- seleção persistente;
- download individual e em lote dos selecionados;
- qualidade original;
- nomes editoriais.

## Aceite

1. processar viagem no Windows;
2. salvar no OMV;
3. importar manifesto no Mac;
4. viagem aparecer na UI;
5. selecionar três arquivos;
6. fechar/reabrir;
7. seleção persistir;
8. baixar somente os três.

---

# Fase 3 — GPS/SRT/telemetria para reduzir trabalho manual

**Prioridade:** P2

## Escopo

- parser SRT tolerante;
- GPS;
- telemetria disponível;
- origem/evidência/confiança;
- reverse geocoding cacheado;
- `poi_suggested` separado de `poi_final`;
- sugestões:
  - órbita;
  - foguete;
  - aproximação;
  - afastamento;
  - deslocamento;
  - panorâmica;
  - `UNKNOWN`;
- correções humanas preservadas;
- pessoas por visão somente se justificar.

---

# Fase 4 — Selects, edição e retenção

**Prioridade:** P3

- in/out;
- selects;
- cortes;
- agrupamento;
- métricas de qualidade;
- retenção/quarentena;
- iCloud/CapCut;
- purge somente com aprovação.

---

# Dependências

```text
Fundação existente
      ↓
Fase 1 — Windows → OMV
classificação + naming + SRT + manifesto
      ↓
Fase 2 — OMV → Mac
SQLite + UI + seleção + download
      ↓
Fase 3
GPS/telemetria + sugestões
      ↓
Fase 4
selects + retenção
```

---

# Definition of Done do MVP útil

## Organizador

Windows processa uma viagem real até o OMV, com:

- MP4/SRT/fotos;
- orientação correta;
- nomes;
- sidecars preservados;
- manifesto;
- origem intacta;
- idempotência.

## Consumo

Mac importa o manifesto e a esposa consegue:

- navegar;
- selecionar;
- fechar/reabrir;
- baixar somente os escolhidos em qualidade original.

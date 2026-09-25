# Drone Media Manager — Fase 3
## Inteligência Editorial, Organização Automática, Scoring e Selects

**Status:** especificação funcional e técnica
**Objetivo:** automatizar a organização editorial de viagens e tomadas, preservando a decisão humana como autoridade final.
**Pré-condição:** Fase 2 suficientemente estável para fornecer catálogo, assets, thumbnails/proxies e UI de revisão.

---

# 1. Visão

A Fase 3 deve transformar o Drone Media Manager em um assistente editorial capaz de ajudar a responder:

- quais arquivos pertencem ao mesmo lugar/contexto;
- como nomear esse grupo;
- qual movimento existe em cada tomada;
- se há pessoas;
- qual é o assunto principal;
- quais tomadas são semelhantes ou redundantes;
- quais têm melhor qualidade;
- quais arquivos/trechos são bons candidatos a selects;
- quais devem ser preparados para edição no CapCut.

Devem existir dois fluxos de primeira classe:

```text
MATERIAL NOVO
MP4 + SRT
→ maior automação

MATERIAL LEGADO
MP4/JPG sem SRT
→ thumbnails + sequência + tempo + análise visual + correção manual rápida
```

Sem SRT não significa sem suporte.

---

# 2. Princípio fundamental

## Automação sugere; humano confirma

Separar sempre:

```text
EXTRAÍDO
  ↓
SUGERIDO
  ↓
CONFIRMADO
```

### Extraído

Dados observáveis:

```text
GPS
timestamp
altitude
velocidade
heading
yaw
gimbal
codec
duração
frames
métricas de imagem
```

### Sugerido

Resultado de algoritmo/API:

```text
location_group_suggested
movement_suggested
people_suggested
subject_suggested
score
select_suggested
```

### Confirmado

Valor final escolhido pelo usuário:

```text
location_group_final
movement_final
people_final
subject_final
tags_final
select_final
```

Regra:

```text
valor humano confirmado
> sugestão automática
> inferência
```

Reprocessamento nunca sobrescreve silenciosamente correção humana.

---

# 3. Local/Grupo substitui POI como conceito central

O usuário não precisa necessariamente de um POI geográfico preciso. Precisa separar conjuntos de arquivos que pertencem ao mesmo contexto editorial.

Exemplos:

```text
Praia do Bode
Cacimba do Padre
Praia da Conceição
Barco Esmeralda do Atlântico
Pórtico Colonial de Socorro
Mirante Central
Casa Airbnb - Chácara Primavera
Rafting
```

Alguns são POIs; outros são referências editoriais.

A entidade central da Fase 3 será:

```text
LocationGroup
```

Na UI:

```text
Local / Grupo
```

Google Places/Geocoding devem sugerir nomes, não definir a verdade.

---

# 4. Hierarquia editorial

```text
Trip
  ↓
LocationGroup
  ↓
Asset
  ↓
Segment
```

## Trip

Exemplo:

```text
Fernando de Noronha - Setembro 2026
Socorro - Agosto 2026
```

## LocationGroup

Conjunto de assets associados ao mesmo contexto.

## Asset

MP4, JPG/JPEG e sidecars relacionados.

## Segment

Trecho temporal de um vídeo quando um arquivo contiver mais de um movimento ou select relevante.

---

# 5. Modelo de dados conceitual

Os nomes podem ser adaptados ao padrão do projeto.

## 5.1 LocationGroup

```text
id
trip_id

name_final
name_source
name_locked

suggested_name
suggestion_confidence
suggestion_provider

sequence_start
sequence_end

start_time
end_time

centroid_lat
centroid_lon

created_at
updated_at
```

`name_source`:

```text
HUMAN
GOOGLE_PLACES
GEOCODING
GPS_CLUSTER
VISUAL_CLUSTER
SEQUENCE
UNKNOWN
```

---

## 5.2 TelemetryTrack

Resumo persistido:

```text
id
catalog_asset_id

parser_version
sample_count

start_time
end_time

start_lat
start_lon
end_lat
end_lon

centroid_lat
centroid_lon

distance_m
altitude_min
altitude_max
altitude_delta

speed_avg
speed_max

heading_delta
yaw_delta
gimbal_yaw_delta
gimbal_pitch_delta

raw_cache_path
created_at
```

Samples completos podem ficar em:

```text
<DERIVATIVES_ROOT>/telemetry/<asset_id>.json.gz
```

ou formato equivalente.

---

## 5.3 EditorialClassification

```text
catalog_asset_id

movement_suggested
movement_confidence
movement_algorithm_version

movement_final
movement_source
movement_locked

people_suggested
people_confidence

people_final
people_source
people_locked

subject_suggested
subject_confidence

subject_final
subject_source
subject_locked
```

---

## 5.4 AssetTag

```text
id
catalog_asset_id
value
source
confidence nullable
created_at
```

Exemplos:

```text
por-do-sol
barco
praia
stand-up
nosso-grupo
rafting
```

---

## 5.5 AssetSegment

```text
id
catalog_asset_id

start_ms
end_ms

movement_suggested
movement_confidence
movement_final
movement_source

technical_score
editorial_score

select_suggested
select_final

created_at
updated_at
```

---

## 5.6 AnalysisSuggestion

Modelo genérico para sugestões:

```text
id
catalog_asset_id
segment_id nullable

kind
value
confidence

algorithm_version
evidence_json

created_at
superseded_at nullable
```

Tipos:

```text
LOCATION_GROUP
MOVEMENT
PEOPLE
SUBJECT
TAG
SCORE
SELECT
```

---

# 6. Correção humana e edição em lote

Todo dado editorial importante deve ser editável:

```text
Local / Grupo
Movimento
Tem pessoas?
Assunto
Tags
Select
IN/OUT
```

Correções humanas registram:

```text
value
actor
timestamp
source = HUMAN
locked = true
```

A UI deve permitir aplicar mudanças a vários assets:

```text
selecionar intervalo
→ aplicar Local
→ aplicar Pessoas
→ aplicar Movimento
→ aplicar Assunto
→ adicionar Tags
```

Cada campo precisa de:

```text
não alterar
```

para não sobrescrever valores diferentes por acidente.

---

# 7. Fase 3A — Agrupamento de filmagens

## Objetivo

Identificar conjuntos consecutivos que provavelmente pertencem ao mesmo local/contexto.

Exemplo:

```text
001–014 → Grupo 1
015–026 → Grupo 2
027–039 → Grupo 3
```

O nome correto do grupo não precisa ser descoberto nesta etapa.

---

## 7.1 Com SRT

Combinar:

```text
ordem
timestamp
GPS
distância
intervalo temporal
telemetria
```

Sinais de fronteira:

```text
mudança geográfica
grande intervalo de tempo
mudança abrupta de contexto
interrupção de sequência
```

---

## 7.2 Sem SRT

Usar:

```text
ordem de filename
data/hora confiável
intervalo temporal
thumbnails
frames representativos
similaridade visual
```

O fluxo manual deve funcionar mesmo sem automação visual.

---

## 7.3 Similaridade visual

Incrementalmente:

```text
frames representativos
→ embedding/representação visual
→ similaridade
→ sugestão de fronteiras
```

Nunca usar similaridade visual isoladamente como verdade.

---

## 7.4 UI de agrupamento

```text
[001] [002] [003] [004] [005]
[006] [007] [008] [009] [010]
[011] [012] [013] [014] [015]
```

Usuário pode:

```text
selecionar 001
SHIFT + selecionar 014
→ Criar grupo
```

ou aceitar:

```text
Grupo sugerido: 001–014
[Confirmar]
[Alterar início]
[Alterar fim]
```

---

## 7.5 Aceite 3A

### Com SRT

Sugerir fronteiras coerentes usando pelo menos:

```text
GPS
tempo
sequência
```

### Sem SRT

Permitir classificar viagem antiga com:

```text
thumbnails
ordem
seleção de intervalo
```

sem baixar/abrir cada MP4 fora do DMM.

---

# 8. Fase 3B — Nome sugerido do Local / Grupo

## Objetivo

Depois de detectar um grupo, sugerir um nome editorial útil.

---

## 8.1 Google integration

Configuração server-side:

```text
GOOGLE_MAPS_API_KEY
```

Usar abstração:

```text
LocationProvider
  suggest_names(lat, lon, radius)
```

Implementações possíveis:

```text
GooglePlacesProvider
GoogleGeocodingProvider
```

A regra editorial não deve depender diretamente da API.

---

## 8.2 Resultado esperado

Exemplo:

```text
Sugestões:

1. Praia do Bode
2. Praia da Conceição
3. Morro do Pico
4. Outro...
```

O usuário pode escolher ou digitar outro nome.

---

## 8.3 Casos sem POI

Deve ser normal usar:

```text
Mirante Central
Rafting
Casa Airbnb
Barco Esmeralda
Pôr do Sol
Estrada para ...
```

sem POI oficial.

---

## 8.4 Cache/custos

- solicitar apenas campos necessários;
- evitar chamadas repetidas para coordenadas próximas;
- persistir identificadores permitidos pelo provider;
- permitir funcionamento manual offline;
- indisponibilidade da API não bloqueia organização.

---

## 8.5 Aceite 3B

Com SRT:

```text
grupo
→ candidatos úteis
→ confirmação/correção
→ nome final persistido
```

Sem SRT:

```text
nome manual
→ funciona normalmente
```

---

# 9. Fase 3C — Classificação automática de movimento

Classes iniciais:

```text
ORBITA
MEIA_ORBITA
FOGUETE
APROXIMACAO
AFASTAMENTO
TRAVELLING
SOBREVOO
PAN
HOVER
SUBIDA
DESCIDA
ESTATICO
UNKNOWN
```

A lista deve ser extensível.

---

## 9.1 Fonte primária

Preferir:

```text
GPS
altitude
velocidade
heading
yaw
gimbal
tempo
```

antes de visão computacional pesada.

---

## 9.2 Regras

### Órbita

Exigir:

```text
trajetória aproximadamente circular
cobertura angular suficiente
raio relativamente estável
translação real
```

```text
drone parado + yaw variando ≠ órbita
```

### Pan

```text
baixa translação
+ yaw significativo
```

### Foguete

```text
grande deslocamento vertical
+ baixa translação horizontal
+ orientação/gimbal compatível
```

### Aproximação/Afastamento

Exigem referencial:

```text
LocationGroup centroid
POI confirmado
subject anchor
```

Sem referência confiável:

```text
UNKNOWN
```

---

## 9.3 Segmentação

Um MP4 pode ter vários movimentos:

```text
00:00–00:05 HOVER
00:05–00:18 ORBITA
00:18–00:26 AFASTAMENTO
```

---

## 9.4 Evidência

Toda sugestão registra:

```text
value
confidence
algorithm_version
evidence
```

Exemplo:

```json
{
  "movement": "ORBITA",
  "confidence": 0.87,
  "evidence": {
    "angular_coverage_deg": 247,
    "radius_variation_pct": 8.3,
    "distance_m": 91
  },
  "algorithm_version": "movement-v1"
}
```

---

## 9.5 Aceite 3C

Dataset real rotulado contendo:

- órbita;
- pan estacionário;
- afastamento;
- aproximação;
- foguete/subida;
- estático;
- ambiguidades.

Medir:

```text
precision
recall
UNKNOWN rate
```

---

# 10. Fase 3D — Pessoas, assunto e tags

Os nomes manuais atuais misturam conceitos:

```text
Afastamento-Pessoas-Barco
MeiaOrbita-NossoGrupo-Barco
Sobrevoo-Barco-DirecaoPordoSol
```

Separar em:

```text
movement
subject
people
people_label
tags
```

---

## 10.1 Pessoas

Primeiro:

```text
YES
NO
UNKNOWN
```

Possível evolução:

```text
NONE
DISTANT
VISIBLE
PROMINENT
```

Detecção visual pode amostrar:

```text
1–2 fps
→ person detector
→ agregação temporal
```

Guardar:

```text
people_suggested
confidence
detected_frames
sampled_frames
```

---

## 10.2 Assunto

Exemplos:

```text
barco
praia
pico
pôr do sol
grupo
cachoeira
igreja
rafting
```

Pode começar manual e ganhar sugestões depois.

---

## 10.3 Aceite 3D

Em 20 arquivos, usuário consegue rapidamente:

- definir grupo;
- marcar pessoas;
- corrigir movimento;
- definir assunto;
- adicionar tags.

Sem mover arquivos fisicamente.

---

# 11. Organização lógica versus física

Classificação passa a viver no banco.

```text
Asset
  location_group_id
  movement_final
  people_final
  subject_final
  tags
```

Alterar classificação não deve exigir mover:

```text
original
SRT
thumbnail
proxy
```

A visão física pode ser materializada apenas na exportação.

---

# 12. Fase 3E — Scoring e redundância

Implementação v1: ranking em `/editorial/`, perfis Instagram/YouTube editáveis,
componentes disponíveis, evidências e histórico em jobs `CALCULATE_SCORE`.
Composição permanece indisponível; avaliação visual usa um thumbnail local.
Operação, fórmulas e limites: [Scoring e redundância](operations/scoring.md).

## Objetivo

Priorizar tomadas boas e reduzir tempo assistindo takes equivalentes.

Não usar um único score opaco.

---

## 12.1 Scores

```text
technical_score
motion_score
composition_score
uniqueness_score
editorial_score
```

### Technical

Pode usar:

```text
sharpness
motion blur
exposição
subexposição
artefatos
jitter
duração útil
```

### Motion

Quando houver telemetria:

```text
suavidade
consistência
yaw
gimbal
aceleração
```

---

## 12.2 Redundância

Comparar dentro de contexto semelhante:

```text
Trip
+ LocationGroup
+ movement
+ subject
```

Exemplo:

```text
Barco Esmeralda
→ Órbita

Take A 91
Take B 87
Take C 72
Take D 65
```

---

## 12.3 Perfis configuráveis

Exemplo:

```text
PROFILE: Instagram

technical     30%
motion        25%
people        10%
duration      10%
composition   15%
uniqueness    10%
```

```text
PROFILE: YouTube

technical     25%
motion        20%
duration      20%
composition   20%
uniqueness    15%
```

Pesos editáveis.

---

## 12.4 Regra

Score pode:

```text
ordenar
destacar
sugerir
```

Score nunca pode:

```text
apagar
descartar definitivamente
```

---

# 13. Fase 3F — Selects automáticos

## Objetivo

Gerar candidatos a arquivos inteiros ou trechos.

Entrada:

```text
LocationGroup
movement
segments
people
subject
scores
redundancy
```

---

## 13.1 SelectCandidate

```text
asset_id
start_ms
end_ms

reason
score

movement
subject
people

selected_final
```

---

## 13.2 UI

```text
[▶ preview]

IN  00:04.200
OUT 00:18.700

Movimento: Órbita
Local: Barco Esmeralda
Score: 88

[Sugerido ✓]

[Usar inteiro]
[Usar trecho]
[Ajustar IN/OUT]
[Rejeitar]
```

---

## 13.3 Exportação

Sempre partir do original.

```text
FAST
stream copy / limites de keyframe

ACCURATE
reencode / frame-exato
```

Gerar:

```text
SELECTS/
selects_manifest.json
selects.csv
```

---

# 14. Fase 3G — CapCut

## CapCut Ready v1 — obrigatório

```text
CAPCUT_READY/
  01_<nome-editorial>.mp4
  02_<nome-editorial>.mp4
  03_<nome-editorial>.mp4

  selects.csv
  selects.json
```

Pode conter:

```text
originais selecionados
ou
selects recortados
```

Esse é o caminho principal e estável.

---

## CapCut adapter v2 — experimental

Somente depois.

Possível automação de projeto/draft deve ficar atrás de:

```text
EXPERIMENTAL_CAPCUT_ADAPTER=true
```

Nunca tornar integração não oficial a única forma de exportação.

---

# 15. Fase 3H — Feedback e calibração

Registrar divergências:

```text
AUTO movement: ORBITA
HUMAN: PAN
```

```text
AUTO local: Praia do Bode
HUMAN: Praia da Conceição
```

Usar para:

```text
ajustar thresholds
ajustar pesos
comparar v1/v2
medir classes problemáticas
```

Métricas por versão:

```text
precision
recall
UNKNOWN rate
acceptance rate
override rate
```

Treino de modelo próprio não é requisito inicial.

---

# 16. Fluxo completo com SRT

```text
Trip
 ↓
MP4 + SRT
 ↓
parse telemetry
 ↓
group boundaries
 ↓
Google suggestions
 ↓
LocationGroup final
 ↓
movement classification
 ↓
people / subject / tags
 ↓
scores
 ↓
redundancy
 ↓
select suggestions
 ↓
human review
 ↓
CapCut Ready
```

---

# 17. Fluxo completo sem SRT

```text
Trip
 ↓
MP4/JPG
 ↓
order + timestamps
 ↓
thumbnails
 ↓
visual grouping suggestions
 ↓
range selection
 ↓
manual LocationGroup
 ↓
manual/visual classification
 ↓
people / subject / tags
 ↓
scores where possible
 ↓
select suggestions
 ↓
CapCut Ready
```

---

# 18. UI mínima da Fase 3

## Tela de viagem

```text
Fernando de Noronha - Setembro 2026

[Todos] [Não classificados] [Sugestões]
```

Grade com thumbnails reais.

## Classificação em lote

```text
[001] [002] [003] [004] [005]
[006] [007] [008] [009] [010]
```

Ações:

```text
Criar grupo
Mover para grupo
Aplicar movimento
Aplicar pessoas
Aplicar assunto
Adicionar tags
```

## Painel de grupo

```text
Praia do Bode

Arquivos: 14
Sugestão automática: 91%

[editar nome]

Takes:
  Órbita       4
  Afastamento  3
  Estático     2
  UNKNOWN      5
```

## Painel de asset

```text
Preview

Local / Grupo
Movimento
Pessoas
Assunto
Tags

Sugestões
Evidências
Scores

Select
IN / OUT
```

---

# 19. Serviços

Separar responsabilidades:

```text
TelemetryService
GroupingService
LocationSuggestionService
MovementClassifier
PeopleDetector
SubjectClassifier
ScoringService
RedundancyService
SelectService
ExportService
```

Não criar um único serviço monolítico de IA.

---

# 20. Versionamento

Toda análise automática registra versão.

Exemplos:

```text
srt-parser-v1
grouping-v1
places-ranking-v1
movement-v1
people-v1
technical-score-v1
select-v1
```

Reprocessamento deve ser auditável.

---

# 21. Jobs

Análises demoradas devem usar jobs persistentes.

```text
PARSE_TELEMETRY
GROUP_TRIP
SUGGEST_LOCATIONS
CLASSIFY_MOVEMENT
DETECT_PEOPLE
CALCULATE_SCORE
BUILD_SELECTS
```

Cada job:

```text
status
progress
error
algorithm_version
started_at
finished_at
```

---

# 22. Degradação graciosa

## Sem SRT

```text
usar modo legado
```

## Google indisponível

```text
localização manual
```

## Detector incompatível

```text
people = UNKNOWN
```

## Movimento inconclusivo

```text
movement = UNKNOWN
```

## Score incompleto

Persistir componentes disponíveis.

Nunca inventar precisão.

---

# 23. Privacidade e APIs externas

Frames/imagens não devem ser enviados para serviço externo sem requisito explícito.

Preferir análise visual local quando possível.

Google:

- chave server-side;
- nunca expor chave no frontend;
- enviar somente coordenadas/dados necessários;
- registrar erros sem credenciais;
- permitir restrições de API.

---

# 24. Testes e dataset de validação

Cada subfase combina:

```text
unitários
integração
fixtures reais
aceite real
```

Criar dataset rotulado:

```text
Trip
asset
location_group esperado
movement esperado
people esperado
subject esperado
quality notes
```

Incluir:

```text
com SRT
sem SRT
vertical
horizontal
pessoa
sem pessoa
órbita
pan
afastamento
aproximação
estático
ambíguo
```

---

# 25. Métricas de produto

Além de precisão, medir tempo economizado:

```text
tempo manual por viagem
tempo com DMM

arquivos abertos manualmente
sugestões aceitas
correções
UNKNOWN
```

O objetivo é reduzir trabalho editorial real.

---

# 26. Ordem de implementação

```text
3A — Agrupamento de filmagens
      ↓
3B — Nome/local sugerido
      ↓
3C — Movimento
      ↓
3D — Pessoas / assunto / tags / correção em lote
      ↓
3E — Scoring / redundância
      ↓
3F — Selects
      ↓
3G — CapCut
      ↓
3H — Feedback / calibração
```

Não implementar tudo em uma única execução.

---

# 27. Critérios globais de aceite

## Material novo

O usuário consegue:

```text
1. importar viagem MP4+SRT;
2. receber grupos prováveis;
3. receber nomes sugeridos;
4. corrigir nomes;
5. receber classificação de movimento;
6. corrigir classificação;
7. marcar/corrigir pessoas e assunto;
8. ordenar takes semelhantes;
9. gerar selects;
10. preparar material para CapCut.
```

## Material legado

O usuário consegue:

```text
1. importar viagem sem SRT;
2. visualizar thumbnails;
3. selecionar intervalos;
4. criar grupos manual/semi-automaticamente;
5. classificar/corrigir em lote;
6. usar scoring quando disponível;
7. gerar selects;
8. preparar CapCut.
```

---

# 28. Definition of Done

A Fase 3 termina quando uma viagem bruta ou um acervo antigo pode evoluir para:

```text
viagem
→ grupos/local
→ takes classificados
→ correções humanas
→ ranking
→ selects
→ CapCut Ready
```

sem depender de organização manual de pastas como fonte de verdade.

---

# 29. Princípios não negociáveis

1. Automação sugere; humano confirma.
2. Correção humana nunca é perdida por reprocessamento.
3. Sem SRT continua plenamente utilizável.
4. `UNKNOWN` é resultado válido.
5. Local editorial não precisa ser POI oficial.
6. Classificação não exige mover arquivos.
7. Score nunca apaga mídia.
8. Proxy nunca vira master.
9. Select deriva do original.
10. CapCut experimental nunca é o único caminho.
11. Algoritmos registram versão e evidência.
12. A UI deve reduzir cliques e tempo de triagem.

---

# 30. Próximo passo

Planejar e implementar apenas:

```text
FASE 3A — Agrupamento de filmagens
```

com suporte explícito a:

```text
SRT presente
SRT ausente
thumbnails
seleção manual por intervalo
correção de fronteiras
persistência de LocationGroup
```

Validar com:

- uma viagem nova com SRT;
- uma viagem antiga sem SRT.

Somente depois avançar para 3B.

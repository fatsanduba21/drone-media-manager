# Aceite real — Fase 1 Windows → OMV

**Data:** 22/09/2026
**Origem:** C:\DMM-TestSource
**OMV:** P:\drone-organizado (UNC: \\OMV-SRV\VOL1_POOL_SSDs\drone-organizado)
**Viagem:** Teste Fase 1
**POI manual:** desconhecido

## Comandos executados

```powershell
.\.venv\Scripts\dmm-organize.exe plan --source 'C:\DMM-TestSource' --trip 'Teste Fase 1' --poi 'desconhecido' --output-omv 'P:\drone-organizado'
.\.venv\Scripts\dmm-organize.exe apply --source 'C:\DMM-TestSource' --trip 'Teste Fase 1' --poi 'desconhecido' --output-omv 'P:\drone-organizado'
.\.venv\Scripts\dmm-organize.exe plan --source 'C:\DMM-TestSource' --trip 'Teste Fase 1' --poi 'desconhecido' --output-omv 'P:\drone-organizado'
.\.venv\Scripts\dmm-organize.exe apply --source 'C:\DMM-TestSource' --trip 'Teste Fase 1' --poi 'desconhecido' --output-omv 'P:\drone-organizado'
```

## Resultado

| Etapa | CREATE/CREATED | ALREADY_OK | CONFLICT | Erros |
| --- | ---: | ---: | ---: | ---: |
| PLAN 1 | 18 | 0 | 0 | 0 |
| APPLY 1 | 18 | 0 | 0 | 0 |
| PLAN 2 | 0 | 18 | 0 | 0 |
| APPLY 2 | 0 | 18 | 0 | 0 |

Foram processados 14 assets lógicos: 2 vídeos INSTAGRAM_9X16 por rotação de 90°,
3 vídeos YOUTUBE_16X9 e 9 fotos FOTOS. Os verticais são 2688x1512
codificados e 1512x2688 exibidos após rotação; os horizontais são 3840x2160. Quatro MP4 tinham SRT pareado;
um MP4 não tinha SRT e foi aceito. Não havia SRT órfão nem arquivo não suportado.

O manifesto está em P:\drone-organizado\teste-fase-1\MANIFESTO.json.
Contém 14 asset_id, metadados ffprobe, fonte da data, POI final, vínculos SRT,
caminhos editoriais e SHA-256 verificados. Vídeos usam mp4_creation_time;
fotos usam dji_filename. Movimento e pessoas ficaram desconhecido.

## Pareamentos, classificação, nomes e destinos

Destinos relativos a P:\drone-organizado.

| Origem | SRT de origem | Classificação | Fonte da data | Destino principal | Destino SRT |
| --- | --- | --- | --- | --- | --- |
| DJI_20260914075956_0013_D.MP4 | DJI_20260914075956_0013_D.SRT | INSTAGRAM_9X16 | mp4_creation_time | teste-fase-1/desconhecido/INSTAGRAM_9x16/2026-09-14_desconhecido_desconhecido_pessoas-desconhecido_9x16_0b1e95e0.mp4 | teste-fase-1/desconhecido/INSTAGRAM_9x16/2026-09-14_desconhecido_desconhecido_pessoas-desconhecido_9x16_0b1e95e0.srt |
| DJI_20260914080044_0014_D.MP4 | DJI_20260914080044_0014_D.SRT | INSTAGRAM_9X16 | mp4_creation_time | teste-fase-1/desconhecido/INSTAGRAM_9x16/2026-09-14_desconhecido_desconhecido_pessoas-desconhecido_9x16_299ae64f.mp4 | teste-fase-1/desconhecido/INSTAGRAM_9x16/2026-09-14_desconhecido_desconhecido_pessoas-desconhecido_9x16_299ae64f.srt |
| DJI_20260914080326_0017_D.MP4 | DJI_20260914080326_0017_D.SRT | YOUTUBE_16X9 | mp4_creation_time | teste-fase-1/desconhecido/YOUTUBE_16x9/2026-09-14_desconhecido_desconhecido_pessoas-desconhecido_16x9_29405b23.mp4 | teste-fase-1/desconhecido/YOUTUBE_16x9/2026-09-14_desconhecido_desconhecido_pessoas-desconhecido_16x9_29405b23.srt |
| DJI_20260914080344_0018_D.MP4 | DJI_20260914080344_0018_D.SRT | YOUTUBE_16X9 | mp4_creation_time | teste-fase-1/desconhecido/YOUTUBE_16x9/2026-09-14_desconhecido_desconhecido_pessoas-desconhecido_16x9_69ebf7dc.mp4 | teste-fase-1/desconhecido/YOUTUBE_16x9/2026-09-14_desconhecido_desconhecido_pessoas-desconhecido_16x9_69ebf7dc.srt |
| DJI_20260914080631_0020_D.MP4 | — | YOUTUBE_16X9 | mp4_creation_time | teste-fase-1/desconhecido/YOUTUBE_16x9/2026-09-14_desconhecido_desconhecido_pessoas-desconhecido_16x9_c98c577f.mp4 | — |
| DJI_20260918130837_0119_D.JPG | — | FOTOS | dji_filename | teste-fase-1/desconhecido/FOTOS/2026-09-18_desconhecido_foto_843bd613.jpg | — |
| DJI_20260918130846_0120_D.JPG | — | FOTOS | dji_filename | teste-fase-1/desconhecido/FOTOS/2026-09-18_desconhecido_foto_6c4f6797.jpg | — |
| DJI_20260918130850_0121_D.JPG | — | FOTOS | dji_filename | teste-fase-1/desconhecido/FOTOS/2026-09-18_desconhecido_foto_255effdb.jpg | — |
| DJI_20260918130904_0122_D.JPG | — | FOTOS | dji_filename | teste-fase-1/desconhecido/FOTOS/2026-09-18_desconhecido_foto_c4ccc77b.jpg | — |
| DJI_20260918130912_0123_D.JPG | — | FOTOS | dji_filename | teste-fase-1/desconhecido/FOTOS/2026-09-18_desconhecido_foto_0273cce2.jpg | — |
| DJI_20260918131140_0126_D.JPG | — | FOTOS | dji_filename | teste-fase-1/desconhecido/FOTOS/2026-09-18_desconhecido_foto_e51f6d15.jpg | — |
| DJI_20260918131148_0127_D.JPG | — | FOTOS | dji_filename | teste-fase-1/desconhecido/FOTOS/2026-09-18_desconhecido_foto_419f7333.jpg | — |
| DJI_20260918131158_0128_D.JPG | — | FOTOS | dji_filename | teste-fase-1/desconhecido/FOTOS/2026-09-18_desconhecido_foto_0db79c3f.jpg | — |
| DJI_20260918131201_0129_D.JPG | — | FOTOS | dji_filename | teste-fase-1/desconhecido/FOTOS/2026-09-18_desconhecido_foto_bc9605bb.jpg | — |

## Verificação física

Get-FileHash -Algorithm SHA256 comparou cada origem com o destino no OMV
e o hash do manifesto: 18/18 coincidiram. Os quatro SRT preservam o basename
do MP4. Há 18 arquivos de mídia no OMV, nenhum .partial, e os 18 arquivos
da origem permaneceram presentes com conteúdo idêntico ao manifesto.
O segundo APPLY não criou novos arquivos.

## Testes e limites da amostra

A suíte completa terminou com 182 testes passando e 1 ignorado. Ruff check,
formatação dos arquivos alterados, mypy e git diff --check passaram.
O gate global ruff format --check . ainda aponta 26 arquivos preexistentes,
fora desta alteração; nenhum dos cinco arquivos Python novos está nessa lista.
A suíte automatizada cobre inventário, classificação 16:9/9:16, display matrix,
4:3/quadrado, JPG/JPEG, SRT órfão, conflito de destino e idempotência.
A amostra real não contém 4:3, quadrado, SRT órfão nem extensão .jpeg;
esses casos foram cobertos por testes. GPS, reverse geocoding, Mac, SQLite
e UI pertencem a fases posteriores.

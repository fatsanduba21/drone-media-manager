# Segmentos do LosslessCut com telemetria (SRT por segmento)

O LosslessCut exporta cortes como
`<original>-HH.MM.SS.mmm-HH.MM.SS.mmm[-segN].MP4` e **descarta** as trilhas de
dados do DJI. O comando `dmm-segments srt` recupera a telemetria do vídeo
original e cria um `.SRT` no formato DJI para cada segmento, com tempo
reiniciado em zero e hora absoluta da gravação. O `dmm-organize` então pareia
cada segmento com seu SRT, e o restante do fluxo (catálogo, agrupamento,
nomes, movimento) funciona sem mudanças.

```powershell
uv run dmm-segments srt "D:\Drone_Temp\Caconde\01-Cristo\Editados"          # simulação
uv run dmm-segments srt "D:\Drone_Temp\Caconde\01-Cristo\Editados" --apply  # grava os .SRT
```

## Fonte da telemetria

Para cada segmento, na pasta do segmento e na pasta acima, nesta ordem:

1. `<original>.SRT` gravado pelo drone;
2. `<original>-stream-N-data-djmd.bin`, extraído pelo LosslessCut;
3. `<original>.MP4`, lendo a trilha `djmd` embutida (DJI Flip).

## Alinhamento com o keyframe

Sem recodificação, o LosslessCut começa o arquivo no keyframe anterior ao
corte pedido. O comando mede a duração real do segmento com `ffprobe` e usa
`fim − duração` como início, se a diferença for de até 5 s. No material de
Caconde a diferença foi de 0,15 s a 1,2 s. `--no-probe` usa os tempos do nome.

## Segurança

- Vídeos, `.bin` e SRTs originais são apenas lidos.
- Um `.SRT`/`.srt` existente nunca é substituído (status `EXISTS`).
- Sem `--apply`, nada é gravado. O relatório JSON lista `CREATE`/`CREATED`,
  `EXISTS` e `NO_TELEMETRY` (código de saída 2).

## Recomendação de fluxo

Ao cortar no LosslessCut, mantenha o `-proj.llc` e exporte também a trilha de
dados (o `-stream-1-data-djmd.bin`), ou preserve o MP4 original. Sem nenhuma
das três fontes, a posição do segmento não pode ser recuperada.

Via Tailscale, o `ffprobe` custa cerca de 3 s por segmento; uma pasta com 23
segmentos levou 74 s em simulação.

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

## Sugestão de cortes antes de abrir no LosslessCut

`dmm-segments suggest` cria, para cada MP4 original, um projeto
`<original>-proj.llc` com o início e o fim parados já marcados como
descartados e o trecho em movimento selecionado. Ao abrir o vídeo, o
LosslessCut carrega o projeto da pasta de saída; ajuste os pontos e divida os
takes normalmente.

```powershell
uv run dmm-segments suggest "D:\Drone_Temp\Caconde\03-Assunto" --output "D:\Drone_Temp\Caconde\03-Assunto\Editados"
uv run dmm-segments suggest "D:\Drone_Temp\Caconde\03-Assunto" --output "D:\Drone_Temp\Caconde\03-Assunto\Editados" --apply
```

Um projeto existente nunca é substituído (status `EXISTS`); `NO_MOTION`
indica um clipe sem trecho em movimento de pelo menos 2 s.

A regra foi calibrada com 22 cortes manuais do DJI Flip (Caconde): em
movimento significa ≥ 0,3 m/s na horizontal, ≥ 0,5 m/s na vertical ou ≥ 2°/s
de gimbal por 1 s, e o trecho mantido começa 0,5 s depois do início do
movimento. Resultado contra os cortes manuais: início a até 1 s em 13 de 22 e
fim a até 1 s em 15 de 22; os demais foram cortes por conteúdo (cena, enquadramento),
que a telemetria não prevê. As divisões internas entre takes não coincidiram
com nenhuma mudança de telemetria e continuam manuais.

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

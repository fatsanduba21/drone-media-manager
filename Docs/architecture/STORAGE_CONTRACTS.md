# Contrato de storage de produção

A raiz OMV no Windows (`--output-omv`) e no Mac (`DMM_OMV_ROOT`) designa o
mesmo diretório compartilhado. O layout escrito por `dmm-organize` é:

```text
<raiz-omv>/
  <trip_slug>/
    MANIFESTO.json
    <pasta-inicial>/
      YOUTUBE_16x9/ | INSTAGRAM_9x16/ | FOTOS/ | OUTROS_REVISAR/
        <nome-fisico>.<mp4|srt|jpg|jpeg>
```

Os caminhos dentro do manifesto são relativos à raiz OMV, usam `/` e começam
com `<trip_slug>/`. MP4 e SRT pareados usam o mesmo basename. O arquivo
`MANIFESTO.json` tem `schema_version: 1`, `trip` e `assets`. Cada asset possui
`asset_id` SHA-256 estável, `classification`, `source`, `video` (ou `null` para
foto), `location`, `editorial` e `output`. `output` contém os caminhos relativos,
hash SHA-256 do original e, quando houver SRT, o caminho e hash dele. O
organizador só publica `verification_status: VERIFIED` após verificar a cópia.
O importador rejeita esquema, paths ou hashes inválidos; `--verify-hash`
recalcula os hashes pelo Mac.

Novos manifestos incluem `naming_scheme: "neutral-v1"`. Sem `--poi`, a pasta
inicial é `a-classificar` e `location.poi_final` é nulo. O nome físico usa
`{data}_{stem-seguro}_{formato}_{id8}`, ou `{data}_{stem-seguro}_foto_{id8}`
para fotos, sem metadados editoriais. O stem é limitado a 48 caracteres;
MP4/SRT pareados compartilham basename. Manifestos antigos sem `naming_scheme`
continuam com os caminhos anteriores; a repetição de PLAN/APPLY não converte
nem renomeia arquivos já publicados. Nomes de grupo confirmado só aparecem
nas cópias baixadas pelo Mac.

`trips/<slug>/00_INBOX_ORIGINALS` e `trips/<slug>-<id>/...` pertencem à
ingestão distribuída **LEGACY/EXPERIMENTAL**. Nenhuma feature nova deve gravar
nesses layouts nem usar o manifesto de `ingest/manifest.py` como substituto de
`MANIFESTO.json`. As tabelas `media_files`/`media_pairs` desse fluxo também não
são o catálogo atual (`catalog_assets`/`asset_files`).

# Organizar mídia no Windows e entregar ao OMV

O comando `dmm-organize` executa a Fase 1 localmente no Windows. Não requer
servidor Mac, SQLite ou `trip_id`. A origem é acessada somente para leitura.

Instale o projeto com `uv sync --all-groups` e confirme que `ffprobe` está no
`PATH`. A raiz do OMV deve estar montada e acessível por UNC ou unidade mapeada.

```powershell
uv run dmm-organize plan `
  --source 'C:\caminho\origem' `
  --trip 'Nome da Viagem' `
  --poi 'Nome do Lugar' `
  --output-omv 'P:\drone-organizado'

uv run dmm-organize apply `
  --source 'C:\caminho\origem' `
  --trip 'Nome da Viagem' `
  --poi 'Nome do Lugar' `
  --output-omv 'P:\drone-organizado'
```

Opcionalmente informe `--movement`, `--people` e `--date YYYY-MM-DD`. Sem data
manual, vídeos usam `creation_time` do MP4 quando válido; arquivos DJI com
timestamp no nome usam esse valor como fallback. O manifesto registra a origem
da data. Se nenhuma fonte estiver disponível, usa `desconhecido`.

O PLAN apresenta inventário, SRT órfãos, arquivos não suportados, metadados,
classificação, nomes, destinos, hashes da origem e preview do manifesto. Não
cria pastas nem copia mídia. Confira `errors` e qualquer arquivo com estado
`CONFLICT` antes de executar APPLY.

O APPLY copia cada arquivo para um temporário, verifica SHA-256, promove para o
nome final e grava `MANIFESTO.json` na pasta da viagem. Destinos divergentes
impedem a operação; um arquivo idêntico recebe `ALREADY_OK`. Repetir PLAN e
APPLY com os mesmos argumentos não duplica arquivos. MP4 e SRT pareados têm o
mesmo basename editorial. O SRT órfão aparece no relatório e não é copiado
isoladamente.

A saída segue `<OMV>/<trip>/<poi>/<categoria>/arquivo`. As categorias são
`YOUTUBE_16x9`, `INSTAGRAM_9x16`, `FOTOS` e `OUTROS_REVISAR`. A pasta da viagem
contém `MANIFESTO.json`, contrato da importação atual no Mac.
No Mac, aponte `DMM_OMV_ROOT` para a mesma raiz compartilhada, execute
`uv run dmm-server migrate` e depois
`uv run dmm-catalog import CAMINHO_DO_MANIFESTO --verify-hash`. Veja o
[contrato de storage](../architecture/STORAGE_CONTRACTS.md) e o
[runbook do Mac](mac-server.md).

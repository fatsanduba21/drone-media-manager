# Fase 1 — ingestão segura distribuída

A origem é sempre somente leitura. O worker Windows enumera MP4/SRT, envia um
snapshot relativo autenticado ao Mac e só copia depois da confirmação humana.
O Mac mantém o SQLite local; o worker nunca abre o banco.

## Fluxo operacional

No Windows, com o ambiente configurado (`DMM_SERVER_URL`, `DMM_WORKER_NAME` e
`DMM_OMV_ROOT`):

```powershell
uv run dmm-worker scan C:\DMM-TestSource
uv run dmm-worker ingest --dry-run C:\DMM-TestSource
uv run dmm-worker submit C:\DMM-TestSource
```

`scan` mostra tipo da fonte, fingerprint, bytes e estados `PAIRED`,
`VIDEO_WITHOUT_SRT` e `ORPHAN_SRT`. `--dry-run` repete descoberta, inventário
e cálculo de capacidade sem criar snapshot, arquivo parcial ou registro. `submit`
cria um snapshot imutável em lotes de até 500 entradas; ele não inicia cópia.

No Mac, depois de conferir a fonte e o destino:

```bash
uv run dmm-server ingest confirm SNAPSHOT_ID --trip TRIP_ID
uv run dmm-server ingest status INGEST_ID
```

A confirmação é somente localhost-admin e valida snapshot finalizado, expiração,
revisão e idempotência. O worker reivindica o job com lease; copia em `.partial`,
registra checkpoints duráveis, calcula SHA-256 independente da origem e destino,
promove sem substituir e então produz o manifesto lógico em `05_MANIFESTS`.

## Códigos de saída

- `0`: operação concluída ou estado `VERIFIED`.
- `2`: argumento, configuração, autenticação ou endpoint inválido.
- `3`: indisponibilidade retomável (`INTERRUPTED`); reconecte a mesma fonte/OMV/Mac
e execute novamente após a reconciliação do lease.
- `4`: conflito ou falha de integridade, como hash divergente, espaço insuficiente
ou destino divergente. Não sobrescreva o destino manualmente.

Uma origem que some, OMV/Mac indisponível ou worker interrompido preserva parciais
e arquivos já verificados. Uma mudança de tamanho/mtime/identidade, hash divergente
ou colisão divergente nunca alcança `VERIFIED`.

## SRT, release e retenção

SRT é opcional: vídeo sem legenda e SRT órfão entram no inventário e manifesto
sem bloquear os demais arquivos. Somente fonte removível pode receber aviso de
liberação do cartão. `REQUIRE_SECOND_COPY` exige uma segunda cópia verificada;
`NAS_ONLY` permite a mensagem após a cópia OMV, com o aviso exato:
“Only one verified copy exists; keep the source card until a second copy is verified.”

A liberação manual do cartão é separada da retenção dos originais em
`00_INBOX_ORIGINALS`. A Fase 1 nunca apaga, move, renomeia ou formata a origem,
e não purga arquivos do INBOX.

## Limites da Fase 1

Não há catálogo DJI, proxies, análise, UI de revisão, selects, retenção automática,
exclusão física ou reverse geocoding. A confirmação administrativa continua
localhost-only até a fase de autenticação/UI.
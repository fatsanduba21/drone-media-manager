# Arquitetura de produção

```text
Cartão ou pasta → Windows dmm-organize → OMV + MANIFESTO.json
                                         ↓
Mac dmm-catalog import → SQLite local → derivados → galeria/download/editorial 3A/3B
```

`dmm-organize` é o produtor oficial do manifesto. Ele faz descoberta, pareamento
MP4/SRT, classificação, cópia com hash independente do destino e publicação
atômica do manifesto. Não requer Mac, banco nem worker. A origem permanece
somente leitura. A configuração `--output-omv` aponta para a mesma raiz que
`DMM_OMV_ROOT` representa no Mac, embora cada sistema a monte por caminho
local diferente.

O Mac é o plano de catálogo e editorial: `dmm-catalog import` valida o
manifesto e registra trips, assets e arquivos no SQLite local. Derivados são
cache local; os downloads leem os originais do OMV. 3A sugere e confirma
grupos, 3B permite nomes manuais ou sugestões do Google Places. A 3C ainda
não faz parte do produto.

O subsistema `dmm-worker` + snapshots/jobs + `00_INBOX_ORIGINALS` permanece no
repositório como **LEGACY/EXPERIMENTAL**. Suas APIs, migrations e runbooks
históricos não são dependências do fluxo acima. Código novo deve seguir
[STORAGE_CONTRACTS.md](STORAGE_CONTRACTS.md).

Para acesso remoto à galeria/editorial, o servidor usa HTTPS e sessão
autenticada. A configuração de produção é `DMM_TLS_CERTFILE` e
`DMM_TLS_KEYFILE` com DNS coberto pelo certificado; veja o
[runbook 2D](../operations/phase-2d.md). `DMM_ALLOW_INSECURE_LAN` não é um modo
suportado para login em produção.

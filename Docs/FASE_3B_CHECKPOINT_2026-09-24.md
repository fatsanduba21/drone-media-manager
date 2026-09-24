# Checkpoint da Fase 3B — nomes de Local / Grupo

**Data:** 24/09/2026

**Base:** `main` em `fb3258b`

**Estado:** implementada e liberada para uso; aceite funcional completo antes da 3C ainda pendente.

## Aceite

- No Mac, após **Sugerir fronteiras** e selecionar um arquivo com GPS no SRT, **Sugerir nomes próximos** retornou candidatos reais, incluindo Praia do Bode e Barraca Recanto do Bode. A usuária confirmou que o fluxo funciona.
- O teste de integração cobre candidato escolhido, confirmação explícita, nome final e Place ID persistidos, edição manual posterior e criação com nome livre quando não há GPS/SRT. A indisponibilidade do Google não impede a organização manual.
- Antes da publicação de `fb3258b`, a suíte registrou 296 testes aprovados e 3 ignorados, com Ruff e mypy aprovados. O teste real no Mac comprovou a consulta de candidatos; a persistência após reinício do serviço não foi observada nessa sessão.

O procedimento está em [operations/location-names.md](operations/location-names.md). A melhoria da sequência de uso na interface fica para uma revisão futura, conforme decisão da usuária.

## Gate de aceite ainda aberto

O teste real acima comprovou a consulta de candidatos, mas não documenta
persistência após reinício nem a matriz completa do
[plano pré-3C](PLANO_SANEAMENTO_PRE_FASE_3C.md): viagem com múltiplos assets,
grupos vazios e movimentação entre grupos (`add`/`replace`), SRTs reais dos
drones usados, grupo sem GPS, indisponibilidade do Places e ausência de chave,
nomes com caracteres portugueses e ausência de alteração dos originais.
Executar essa matriz no Mac/OMV e registrar evidência antes de mudar o estado
para **PHASE 3B — ACCEPTED**.

## Regressão real com `noronha-teste` (24/09/2026)

Resultados informados pela usuária nesta sessão:

- Windows → OMV: primeiro `apply` com 18 `CREATED`, zero erros; repetição com
  zero `CREATED`, 18 `ALREADY_OK`, zero erros e `MANIFESTO.json` publicado.
- Mac: `preview --verify-hash` com 11 assets, 18 arquivos disponíveis, zero
  ausentes e conflitos; importação com 11 assets e 18 arquivos criados;
  repetição com zero criações e 11 `already_imported`.
- Derivados: 19 gerados, zero falhas; repetição com 19 reutilizados e zero falhas.
- Galeria: listagem, mídia, seleção e download passaram no teste informado.
- Editorial: sugestões e alteração de alguns nomes funcionaram no teste
  informado. Um backup do SQLite foi concluído antes da migração
  `0008_capture_time`. A nova importação reconheceu 11 assets e 18 arquivos
  disponíveis, sem criar registros ou apontar conflitos. Após a atualização
  no Mac, a usuária confirmou que a ordenação por horário de captura e o filtro
  do editorial funcionaram. Ainda faltam evidências dos demais itens da matriz
  3B, inclusive persistência após reinício.

Achados de uso real a priorizar separadamente do aceite funcional:

- O organizador usa `desconhecido` como valor padrão de movimento e pessoas e
  incorpora ambos ao nome físico. O nome de grupo confirmado vive no catálogo;
  renomear os originais já importados exige revisar o contrato Windows → OMV.
- A ordenação por `video.creation_time`, com fallback determinístico, e o filtro
  **Sem grupo/Com grupo** foram implementados na branch de saneamento e
  validados no Mac pela usuária.
- Selecionar na galeria ainda recarrega a página. Exibir grupos editoriais na
  galeria, alterar nomes apenas na cópia baixada e oferecer seleção em massa
  continuam como melhorias futuras. O plano está em
  [`superpowers/plans/2026-09-24-deferred-editorial-improvements.md`](superpowers/plans/2026-09-24-deferred-editorial-improvements.md).

Revisão M11 no código: `assign_range` cobre `add` (preserva membros) e
`replace` (remove membros fora do intervalo), inclusive ao mover assets entre
grupos; os testes de persistência cobrem esses casos. Um grupo pode ficar
vazio após a movimentação e continua listado, sem ação de exclusão na API ou
na interface. A decisão sobre excluir grupos vazios deve ser tomada no aceite
real antes de 3C consumir os grupos; nenhuma exclusão automática foi presumida.

## Preparação da Fase 3C

A seção 9 de [03_FASE_3_INTELIGENCIA_EDITORIAL_E_ORGANIZACAO_AUTOMATICA.md](03_FASE_3_INTELIGENCIA_EDITORIAL_E_ORGANIZACAO_AUTOMATICA.md) define classificação de movimento por segmentos, com evidência, confiança e versão do algoritmo. O parser atual `grouping/telemetry.py` entrega apenas contagem, início, fim, centroide e horário; ele não conserva a trajetória por amostra nem extrai altitude, yaw ou gimbal. Esse é o primeiro requisito técnico a resolver para classificar movimentos com base em telemetria.

Antes de implementar o classificador, reunir e rotular vídeos reais de órbita, pan estacionário, aproximação, afastamento, foguete/subida, estático e casos ambíguos. Medir precisão, recall e taxa de `UNKNOWN`. Aproximação e afastamento exigem um referencial confiável; sem ele, usar `UNKNOWN`. Um vídeo pode conter mais de um segmento.

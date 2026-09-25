# Drone Media Manager — Plano de Saneamento Pré-Fase 3C

**Data:** 24/09/2026

## 1. Objetivo

Estabilizar a arquitetura e consolidar a `main` antes da Fase 3C, evitando carregar branches divergentes, contratos antigos, código morto e documentação desatualizada.

## 2. Arquitetura oficial confirmada

O fluxo de produção é:

```text
Cartão/pasta
   -> Windows: dmm-organize (descoberta, organização, cópia/verificação)
   -> OMV: originais organizados + MANIFESTO.json
   -> Mac mini: dmm-catalog import
   -> SQLite + derivatives + galeria/editorial
   -> 3A agrupamento -> 3B nomes -> 3C...
```

Decisões:

- `dmm-organize` é o produtor oficial do `MANIFESTO.json`.
- O Mac é o plano de catálogo e inteligência editorial.
- O worker distribuído (`dmm-worker` + snapshots/jobs + `00_INBOX_ORIGINALS`) não é o fluxo oficial e não deve ditar prioridades.
- A Fase 2E está **ACEITA**: o teste ponta a ponta foi executado manualmente. Automatização adicional é melhoria operacional.
- A Fase 3B está **ACEITA**, por confirmação explícita da usuária em 25/09/2026; evidências e limites estão no [checkpoint](FASE_3B_CHECKPOINT_2026-09-24.md#confirmação-da-usuária-e-aceite-25092026).

## 3. Reclassificação dos achados

### P0 — Bloqueador estrutural real: `dmm-organize` fora da `main`

Este é o achado mais importante do relatório. Uma instalação limpa da `main` não representa hoje o produto real, pois consome `MANIFESTO.json`, mas o produtor está na branch `codex/phase-1-windows-omv`.

**Ação:** trazer seletivamente `cli/organize.py`, `organize.py`, testes, entry point, documentação e dependências necessárias para a `main`.

**Não fazer merge cego da branch antiga.** Comparar os commits `a2b97db` e `1a1de0b` com a `main` atual e portar/cherry-pick apenas o que continua válido.

### Itens do worker que deixam de ser bloqueadores

C2, C3, C4, A1, A3, A5, A6, M2, M3, M4, M5, M6 e M13 são problemas reais se o worker distribuído for produto suportado. Como esse fluxo não é o caminho escolhido, não vale gastar a etapa pré-3C corrigindo-o.

**Ação:** marcar o subsistema como `LEGACY/EXPERIMENTAL`, retirá-lo dos runbooks principais e impedir que novas fases dependam dele. A remoção física pode ocorrer depois.

### Itens do fluxo atual que permanecem relevantes

- **A4 — galeria O(n²)/I/O SMB:** importante para escala, mas medir antes de otimizar.
- **M7 — derivatives recalculando hashes e sem timeout:** backlog importante do fluxo oficial.
- **M10 — análise/Places síncronos:** validar no aceite 3B; corrigir antes da 3C apenas se causar travamento real.
- **M11 — gestão de grupos incompleta:** merece revisão antes da 3C, pois 3C consumirá o estado produzido por 3A/3B.
- **M12 — parser SRT limitado:** testar com SRTs reais dos drones utilizados; suporte histórico pode ficar no backlog.
- **A2/TLS e docs:** consolidar uma configuração LAN suportada e remover instruções conflitantes.

## 4. Plano de execução

### Etapa 0 — Branch e baseline

Criar:

```text
chore/pre-phase-3c-codebase-consolidation
```

Registrar commit da `main`, migrations, branches e baseline de testes. O relatório registrou:

```text
296 passed
3 skipped
153 warnings
```

**Aceite:** nenhum teste existente deve regredir durante o saneamento.

### Etapa 1 — Recuperar e consolidar `dmm-organize`

Comparar `main` com `codex/phase-1-windows-omv`, especialmente `a2b97db` e `1a1de0b`.

Revisar e trazer:

- `cli/organize.py`;
- implementação de organização;
- testes;
- entry point no `pyproject.toml`;
- contratos/schema do manifesto;
- documentação operacional;
- dependências/configurações associadas.

Após cada grupo lógico, rodar testes.

**Aceite:** em clone limpo da futura `main`, `dmm-organize --help` existe e o fluxo Windows -> OMV -> `MANIFESTO.json` funciona sem outra branch.

### Etapa 2 — Consolidar documentos

Separar documentação normativa atual de histórico/prompts antigos. Estrutura sugerida:

```text
Docs/
  README.md
  architecture/
    CURRENT_ARCHITECTURE.md
    DATA_FLOW.md
    STORAGE_CONTRACTS.md
  specs/
  checkpoints/
  operations/
  archive/
    prompts/
    old-plans/
    distributed-ingest/
```

Não é obrigatório usar exatamente essa árvore; é obrigatório deixar inequívoco o que é fonte de verdade.

Criar `CURRENT_ARCHITECTURE.md` declarando explicitamente o fluxo Windows -> OMV -> Mac e que `dmm-worker` não pertence ao fluxo de produção atual.

### Etapa 3 — Atualizar status da Fase 2E

Atualizar/criar checkpoint:

```text
PHASE 2E — ACCEPTED
```

Registrar que o aceite funcional ponta a ponta foi concluído manualmente. Se houver automatização pendente, classificá-la como melhoria operacional, não como aceite pendente.

### Etapa 4 — Unificar contratos de storage

O relatório encontrou três contratos concorrentes:

```text
<slug>/<poi>/<categoria>
trips/<slug>/00_INBOX_ORIGINALS
trips/<slug>-<id>/...
```

Documentar o layout produzido pelo `dmm-organize` como **único contrato de produção**. Código que implemente layouts antigos deve ser marcado como legado, isolado ou removido.

**Aceite:** existe um único contrato de storage que novas features devem usar.

### Etapa 5 — Auditoria de código morto/legado

Classificar cada componente não utilizado como:

```text
ACTIVE
PLANNED
LEGACY
DEAD
```

Revisar pelo menos:

- `run_preflight`;
- `evaluate_release`;
- `DestinationPlanner`;
- `IngestRepository`;
- `IngestService`;
- `discover_removable_sources`;
- `media_files`;
- `media_pairs`;
- `file_operations`;
- subsistema worker/jobs/snapshots.

`DEAD` deve ser removido. `LEGACY` deve ser isolado. `PLANNED` precisa de referência concreta no roadmap.

### Etapa 6 — Revisar migrations/schema sem reescrever história

Mapear cada tabela por subsistema, writer, reader e status atual. Dar atenção às tabelas do ingest antigo.

Não é necessário remover tabelas legadas antes da 3C. **Não reescrever migrations históricas já aplicadas.** Se houver remoção futura, criar migration nova.

**Aceite:** banco vazio chega ao head; banco existente migra; código novo não depende acidentalmente de tabelas legadas.

### Etapa 7 — Aceite formal da 3B

Antes da 3C, testar com viagem real:

- viagem e assets carregam em ordem;
- grupos 3A são preservados;
- telemetria real é lida;
- centro do grupo é calculado;
- Google Places retorna sugestões coerentes;
- comportamento sem API key é correto;
- falha do Places é tratada;
- renomeação manual funciona;
- persistência após restart;
- caracteres portugueses;
- grupos sem GPS;
- grupos com múltiplos assets;
- nenhum original é alterado/movido inesperadamente.

Revisar especificamente M11: grupos vazios, movimentação entre grupos, `add`/`replace` e necessidade de exclusão.

**Aceite:** checkpoint `PHASE 3B — ACCEPTED`.

### Etapa 8 — Regressão ponta a ponta

Rodar novamente:

```text
Windows -> dmm-organize -> OMV -> MANIFESTO
Mac -> import -> derivatives -> galeria
login -> seleção -> download
editorial 3A -> 3B
```

Isso é especialmente importante depois de consolidar a Fase 1 na `main`.

## 5. Gate obrigatório para iniciar 3C

### Repositório
- [ ] `dmm-organize` está na `main`.
- [ ] testes do organizador estão na `main`.
- [ ] entry point está correto.
- [ ] nenhuma operação de produção depende de branch paralela.
- [ ] documentos normativos estão na `main`.

### Arquitetura
- [ ] Windows -> OMV -> Mac documentado como fluxo oficial.
- [ ] `MANIFESTO.json` documentado como contrato.
- [ ] worker distribuído explicitamente legado/experimental ou removido.
- [ ] um único layout de storage é produção.
- [ ] código morto/legado classificado.

### Banco
- [ ] migrations chegam ao head em banco vazio.
- [ ] banco existente migra.
- [ ] tabelas legadas identificadas.
- [ ] migrations históricas aplicadas não foram reescritas.

### Testes
- [ ] baseline continua passando.
- [ ] testes recuperados do `dmm-organize` passam.
- [ ] Windows -> OMV -> manifesto passa.
- [ ] import no Mac passa.
- [ ] derivatives passam.
- [ ] galeria passa.
- [ ] seleção/download passam.

### Fases
- [ ] 2E = ACCEPTED.
- [ ] 3A permanece aceita.
- [ ] 3B testada com material real.
- [x] 3B = ACCEPTED (aceite da usuária em 25/09/2026).
- [ ] bugs da 3B que afetem contratos da 3C resolvidos.

## 6. Ordem recomendada

```text
1. Criar branch de saneamento
2. Registrar baseline
3. Comparar branch antiga do dmm-organize
4. Recuperar dmm-organize + testes + entry point
5. Rodar testes
6. Consolidar documentação
7. Declarar arquitetura oficial
8. Atualizar 2E para ACCEPTED
9. Isolar worker/ingest legado
10. Unificar contrato de storage
11. Classificar código morto/legado
12. Auditar schema/migrations
13. Testar 3B em material real
14. Corrigir bugs estruturais encontrados
15. Marcar 3B ACCEPTED
16. Rodar regressão ponta a ponta
17. Merge da branch de saneamento na main
18. Criar branch da Fase 3C
```

## 7. Instrução para Codex/Claude Code

O objetivo desta etapa **não é implementar a Fase 3C**.

Primeiro, executar o saneamento acima. Para cada mudança:

1. mostrar evidência no codebase;
2. explicar se é `ACTIVE`, `LEGACY`, `DEAD` ou `PLANNED`;
3. evitar merge cego de branches antigas;
4. preservar migrations históricas;
5. rodar testes após cada conjunto lógico;
6. atualizar docs junto com a mudança;
7. não corrigir o worker legado apenas para satisfazer o relatório;
8. não iniciar 3C enquanto o gate deste documento não estiver concluído.

## 8. Resultado esperado

Depois deste saneamento, a `main` deve representar sozinha o produto que realmente existe:

```text
Windows
  dmm-organize
       |
       v
OMV + MANIFESTO.json
       |
       v
Mac mini
  catalog
  derivatives
  gallery
  editorial
       |
       +-- 3A
       +-- 3B
       +-- 3C (próxima fase)
```

A principal meta não é chegar a “zero issues”, e sim remover a ambiguidade arquitetural antes que novas fases sejam construídas sobre contratos ou subsistemas abandonados.

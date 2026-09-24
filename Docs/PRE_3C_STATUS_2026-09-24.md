# Estado do saneamento pré-3C

**Branch:** `chore/pre-phase-3c-codebase-consolidation`

**Base:** `main` em `5d2420d29b7dfbba3ad998a28c622f90f3beae21`

**Baseline:** 296 passed, 3 skipped, 153 warnings.

**Após port e saneamento local:** 309 passed, 3 skipped, 153 warnings;
`ruff check .`, mypy e Ruff format nos cinco arquivos Python do port passam.

| Gate | Estado | Evidência |
| --- | --- | --- |
| Produtor do manifesto | Implementado na branch de saneamento | Port seletivo de `a2b97db` (`organize.py`, CLI, testes e runbook); checkpoint real da Fase 1 de `1a1de0b`. Sem merge da branch antiga. |
| Entry point e handoff | Verificado localmente | `dmm-organize --help`; teste integra `build_plan`/`apply_plan` ao `dmm-catalog import --verify-hash` em OMV e SQLite temporários. |
| Arquitetura/storage | Documentado | `Docs/README.md` e `Docs/architecture/`; worker e layout `00_INBOX_ORIGINALS` classificados como legados. |
| Código morto/schema | Auditado | `IngestService` sem chamadores removido; inventário de componentes e tabelas em `architecture/LEGACY_INVENTORY.md`. Migrations históricas intactas. |
| Migrations | Verificado em testes temporários | Banco vazio sobe ao head; bancos existentes em `0005_gallery_auth` e `0005_grouping` convergem para `0007_location_names` preservando dados. |
| Fase 2E | ACCEPTED | Decisão manual registrada em `FASE_2E_CHECKPOINT_2026-09-24.md`. |
| Fase 3B | Pendente aceite ampliado | Teste real anterior comprovou Places; falta matriz do plano pré-3C e persistência após restart. |
| Regressão real ponta a ponta | Pendente | Repetir no Windows, OMV e Mac com viagem real antes de integrar à `main`. |

O check global `ruff format --check .` encontra dívida preexistente em arquivos
fora deste port; a formatação dos arquivos Python recuperados é verificada
separadamente. A4 (escala da galeria) e M7 (hash/timeout de derivatives) ficam
no backlog até haver medição, conforme o plano. M10 (Places síncrono), M11
(grupos vazios) e M12 (SRT real) dependem da matriz de aceite 3B; o estado
observado de M11 está no checkpoint da 3B.

Não iniciar 3C nem integrar esta branch à `main` antes de concluir os dois
gates reais acima e registrar a decisão de aceite da 3B.

# Documentação atual

1. [Arquitetura de produção](architecture/CURRENT_ARCHITECTURE.md) — fluxo e responsabilidades.
2. [Contrato de storage e manifesto](architecture/STORAGE_CONTRACTS.md) — único layout para código novo.
3. [Inventário legado e schema](architecture/LEGACY_INVENTORY.md) — classificação de componentes e tabelas.
4. Runbooks atuais em `operations/`: `windows-organize.md`, `mac-server.md`,
   `derivatives.md`, `phase-2d.md`, `grouping.md`, `location-names.md` e
   [movimento (3C)](operations/movement.md).
5. Checkpoints em `FASE_*_CHECKPOINT_*.md` e `FASE_1_ACEITE_REAL_2026-09-22.md`.

O [estado pré-3C](PRE_3C_STATUS_2026-09-24.md) e o
[roteiro de aceite real](operations/pre-3c-real-acceptance.md) acompanham os
gates ainda abertos.

`Specs/`, `superpowers/`, prompts e planos numerados registram decisões e
implementações anteriores. Quando divergirem dos três contratos acima, são
históricos. `PLANO_SANEAMENTO_PRE_FASE_3C.md` registra o gate de preparação.

O runbook `operations/safe-ingest.md`, `operations/windows-worker.md` e o
checkpoint `testing.md` de ingestão distribuída descrevem o subsistema
**LEGACY/EXPERIMENTAL**. Não são instruções para uma viagem nova.

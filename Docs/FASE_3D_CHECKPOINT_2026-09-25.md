# Fase 3D — classificação editorial

A primeira versão permite classificar em lote os assets selecionados por grupo,
pessoas (YES/NO/UNKNOWN), movimento, assunto, identificação das pessoas e tags.
Cada campo começa em “Não alterar” ou vazio, e só valores informados são
aplicados. Tags podem ser adicionadas e removidas sem apagar as demais.

As escolhas de pessoas/assunto/rótulo têm fonte HUMAN, ator, timestamp e
bloqueio de revisão. O movimento usa a revisão confirmada da Fase 3C. Tudo
fica em SQLite local, sem mover mídia e sem exigir SRT ou rede. Reimportação e
reanálise não substituem escolhas humanas.

Detecção visual de pessoas e sugestões automáticas de assunto permanecem como
evoluções opcionais da especificação. A etapa atual começa manualmente, como
previsto nas seções 10.1 e 10.2; UNKNOWN é exibido quando não há confirmação.

Após atualizar o Mac: `git pull`, `uv sync --all-groups` e
`uv run dmm-server migrate` antes de iniciar o servidor. O banco local deve
ter backup operacional antes da migração, conforme o procedimento existente.

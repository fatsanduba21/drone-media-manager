# Fase 3D — classificação editorial

A primeira versão permite classificar em lote os assets selecionados por grupo,
pessoas (YES/NO/UNKNOWN), movimento, assunto, identificação das pessoas e tags.
Em uma seleção existente, os valores salvos em comum aparecem para edição;
valores diferentes ficam em “Não alterar” ou vazios. Só mudanças informadas
são aplicadas. Tags podem ser adicionadas e removidas sem apagar as demais.

As escolhas de pessoas/assunto/rótulo têm fonte HUMAN, ator, timestamp e
bloqueio de revisão. O movimento usa a revisão confirmada da Fase 3C. Tudo
fica em SQLite local, sem mover mídia e sem exigir SRT ou rede. Reimportação e
reanálise não substituem escolhas humanas.

Detecção visual de pessoas e sugestões automáticas de assunto permanecem como
evoluções opcionais da especificação. A etapa atual começa manualmente, como
previsto nas seções 10.1 e 10.2; UNKNOWN é exibido quando não há confirmação.

## Aceite

**Concluída por aceite do usuário em 2026-09-25.** Ele testou pessoas,
movimento, tags e nomes de pessoas e relatou que funcionaram a contento.
Após esse teste, a galeria passou a mostrar os valores salvos nos cartões e a
preencher os campos comuns ao selecionar novamente os arquivos; o usuário
confirmou a conclusão da 3D. Não há registro de medição cronometrada com 20
arquivos, portanto esse número não é apresentado como resultado observado.

Após atualizar o Mac: `git pull`, `uv sync --all-groups` e
`uv run dmm-server migrate` antes de iniciar o servidor. O banco local deve
ter backup operacional antes da migração, conforme o procedimento existente.

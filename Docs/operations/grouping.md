# Fase 3A — agrupamento editorial

A fase 3A usa o catálogo da 2A e os thumbnails da 2B. A análise SRT gera **sugestões**; somente a ação na galeria cria ou altera um grupo confirmado. Os arquivos originais, SRTs e derivados permanecem nos caminhos atuais.

## Preparar no Mac

1. Atualize o checkout e execute `uv run dmm-server backup` antes da migração. Guarde o caminho e SHA-256 exibidos.
2. Execute `uv run dmm-server migrate` para aplicar `0005_grouping` e a revisão de união `0006_merge_2d_3a`. Bancos já migrados na fase 2D mantêm usuários e seleções.
3. Confirme que a viagem está importada no catálogo. Se faltarem thumbnails, execute `uv run dmm-derivatives generate --trip SLUG`.
4. Reinicie o servidor e abra `https://NOME_DNS_DO_CERTIFICADO:8000/editorial/`. Entre com o mesmo usuário da galeria se a página solicitar login.

A página e a API editorial exigem HTTPS e a sessão autenticada da galeria, inclusive quando `DMM_BIND_HOST` aponta para o Tailscale. Ações de escrita exigem o token CSRF da sessão. A interface não expõe os originais; ela serve apenas thumbnails READY do cache local, com caminho validado.

## Revisar uma viagem

- Escolha a viagem e clique em **Sugerir fronteiras**. A operação lê SRTs disponíveis e usa GPS, hora confiável e interrupções da sequência de nomes.
- Revise as sugestões na folha de contato. Clique no primeiro arquivo e use **Shift + clique** no último para selecionar um intervalo inclusivo.
- Informe um nome ou use o nome provisório `Grupo N`; clique em **Criar grupo**. Uma sugestão também pode ser confirmada diretamente.
- Para corrigir fronteiras, selecione o novo intervalo, escolha o grupo existente e clique em **Aplicar intervalo ao grupo**.
- Uma viagem sem SRT continua organizável pela ordem dos arquivos, thumbnails e intervalos manuais. Se um thumbnail estiver ausente, a grade mostra o nome do arquivo e um aviso; gere novamente os derivados.

Reprocessar não modifica grupos confirmados. Cada execução guarda novas sugestões e marca as anteriores como substituídas. A interface não mostra percentuais de confiança porque o algoritmo inicial ainda não foi calibrado com viagens reais.

## Aceite com material real

1. Em uma viagem nova com MP4+SRT, conferir manualmente se as fronteiras propostas correspondem a mudanças de GPS, hora e sequência. Confirmar um grupo, reprocessar e verificar que o nome e os membros confirmados persistem.
2. Em uma viagem antiga sem SRT, conferir thumbnails reais, selecionar um intervalo com Shift, criar um grupo e corrigir suas fronteiras sem abrir cada MP4 fora do DMM.
3. Reiniciar o servidor e verificar a persistência dos grupos.

A fase 3A não calcula similaridade visual nem sugere nomes de POI. Esses sinais podem ser adicionados sem substituir as decisões já confirmadas.

# Prompt para a Fase 2E — aceite end-to-end real

Execute somente a Fase 2E descrita em Docs/02_FASE_2_OMV_MAC_GALERIA_SELECAO_DOWNLOAD.md. Comece da branch remota origin/codex/phase-2d-selection-download, no HEAD confirmado após o fechamento da 2D, em um worktree isolado. Inspecione o estado de Git e os documentos do projeto antes de agir. Preserve o checkout principal, os demais worktrees, as alterações não rastreadas, o banco, o .env, o cache e os arquivos do OMV. Não faça merge nem push para main.

Contexto confirmado: a 2D entrega login HTTPS, seleção persistida em SQLite e downloads de cada ORIGINAL separadamente, sem ZIP. O Mac mini exigiu uma autorização gráfica de acesso ao disco para uv; após concedê-la, os downloads funcionaram. O usuário comparou os SHA-256 dos originais baixados com os hashes dos AssetFile ORIGINAL e informou que todos coincidiram. Leia Docs/FASE_2D_CHECKPOINT_2026-09-23.md e Docs/operations/phase-2d.md. O aceite completo no MacBook da usuária ainda não foi feito.

Objetivo: comprovar, com a usuária no MacBook da LAN e com o Windows desligado, que a triagem e o download funcionam sem acessar pasta bruta, acervo completo ou iCloud. Chrome é o navegador padrão; Safari pode servir como comparação ou alternativa para links individuais. Não peça senhas, cookies, tokens, conteúdo do .env ou arquivos de mídia ao usuário. Oriente comandos em etapas curtas, próprios para alguém leigo, e registre somente resultados e hashes necessários.

Roteiro de aceite:

1. Confirme OMV e Mac mini ligados; registre o commit em execução, HTTPS confiável e /health com banco, OMV, ffmpeg, ffprobe e worker saudáveis. Se houver falha, investigue e corrija apenas o defeito necessário.
2. Com o Windows desligado, no MacBook da usuária, abra a aplicação via HTTPS, autentique e abra a viagem real de teste. Confirme 14 assets.
3. Aplique o filtro INSTAGRAM_9X16; abra um proxy e faça seek. Registre se reprodução e busca funcionaram.
4. Selecione exatamente três assets, anote IDs e contagem, feche o Chrome completamente, reabra, autentique se solicitado e confirme a persistência das mesmas três seleções.
5. Clique em Baixar selecionados e aceite a permissão de downloads múltiplos do Chrome, se solicitada. Confirme exatamente três arquivos ORIGINAL separados, sem ZIP e sem descompactação, com nomes editoriais. Compare o SHA-256 de cada arquivo recebido no MacBook com o AssetFile ORIGINAL catalogado, vinculando cada hash ao asset_id. Teste também o link individual Baixar original. Se o lote falhar, use os links individuais e registre o defeito do lote.
6. Em janela anônima, confirme que originais, miniaturas e proxies não são acessíveis sem sessão; registre o comportamento da galeria. Confira /health novamente.
7. Registre um relatório de aceite com data, ambiente, navegador, commit, passos, evidências, pendências e decisão PASSA/FALHA. Diferencie observação real de teste automatizado. Se depender de ação presencial ou do MacBook, deixe PENDENTE e dê a próxima instrução concreta; não declare a 2E concluída sem o cenário integral.

Mantenha o fluxo sem ZIP. Não importe manifesto novamente nem regenere derivados. Não amplie a fase para GPS/SRT completo, tags, scoring, CapCut, iCloud, retenção ou purge. Se precisar alterar código ou documentação para corrigir um defeito, use testes que reproduzam o problema, rode a suíte relevante e os checks de qualidade, documente o resultado e faça commits na branch da 2E. Só publique a branch quando o estado estiver verificável e autorizado pelo pedido em curso.

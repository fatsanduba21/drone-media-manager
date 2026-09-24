# Fase 3B — nomes de Local / Grupo

No Mac, faça backup do banco com `uv run dmm-server backup`, atualize o checkout e execute `uv run dmm-server migrate`. A revisão `0007_location_names` adiciona um Place ID opcional aos grupos existentes sem alterar seus nomes nem membros.

Para habilitar sugestões do Google Places, configure `GOOGLE_MAPS_API_KEY` apenas no `.env` do servidor Mac. A chave precisa ter acesso à Places API (New). Sem chave, sem rede ou sem GPS no SRT, a organização manual continua disponível. A chave não é enviada ao navegador.

Na página `/editorial/`, escolha a viagem e execute **Sugerir fronteiras** para ler a telemetria. Selecione um intervalo e clique em **Sugerir nomes próximos**. Os candidatos são consultados em um raio de 500 m, com um cache local de cinco minutos para coordenadas próximas. A interface mostra a atribuição Google Maps junto aos resultados. Clique em um candidato ou digite qualquer nome editorial e então clique em **Criar grupo**. Para um grupo existente, use **Editar nome**, corrija o campo e clique em **Renomear grupo**.

A busca não cria nem renomeia grupos. O nome final só muda após confirmação. Uma edição manual remove o vínculo com o Place ID. O sistema guarda somente o Place ID permitido e o nome final confirmado; candidatos não são gravados no banco. Viagens sem SRT usam o mesmo campo de nome manual, sem exigir uma consulta externa.

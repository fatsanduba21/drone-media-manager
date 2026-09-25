# Scoring e redundância — Fase 3E

Execute `uv run dmm-server migrate` e reinicie o servidor. A migração
`0011_scoring` adiciona apenas `scoring_profiles`; não modifica mídia nem
classificações. No Windows/Codex, inicialize `scripts/dev-env.ps1` antes do uv.

Em `/editorial/`, escolha a viagem e abra **Ranking de tomadas**. Escolha Instagram
ou YouTube, ajuste os pesos se necessário e clique em **Calcular ranking**.
O cálculo salva os pesos editados. Os pesos são compartilhados no servidor;
execuções anteriores preservam os pesos usados. **Atualizar resultado** recupera
o estado após recarregar a página. Uma análise interrompida pode ser recalculada.

O ranking permite filtrar por grupo, abrir o preview original da galeria e
revisar takes visualmente semelhantes. A grade continua em ordem sequencial para
preservar seleção por intervalo. Nada é selecionado, movido ou apagado pelo score.

## Componentes e limites

Todos os scores ficam entre 0 e 100. `null`/“—” significa sem evidência, inclusive
sem SRT, cache ausente, thumbnail inválido e composição ainda não avaliada.

| Componente | Evidência / fórmula v1 |
|---|---|
| Técnica | Um thumbnail local, convertido para cinza em 128 × 128. Média de nitidez (`min(100, média das bordas × 5)`) e exposição (`100 × fração de pixels entre 8 e 247`). |
| Movimento | Telemetria temporal disponível: aceleração de velocidade e aceleração angular de yaw/gimbal. Penalidades normalizadas em 5 m/s², 30 graus/s² (yaw) e 20 graus/s² (pitch). Yaw considera volta de 360°. Exige três amostras consecutivas válidas, intervalos de até 5 s. |
| Composição | Não avaliada nesta versão; permanece indisponível. |
| Pessoas | Preferência editorial: YES = 100, NO = 0; UNKNOWN indisponível. Não mede qualidade técnica. |
| Duração | `min(100, duração_ms / 100)`: satura em 10 s. Mede duração total; não detecta trechos úteis. Sem duração válida, indisponível. |
| Unicidade | `min(100, menor distância dHash / 32 × 100)` entre thumbnails comparáveis no mesmo contexto. Sem pares avaliáveis, indisponível. |
| Editorial | Média ponderada dos componentes disponíveis com peso positivo. Cobertura = fração dos pesos com evidência. |

Instagram inicia em 30/25/10/10/15/10; YouTube em 25/20/0/20/20/15
(técnica/movimento/pessoas/duração/composição/unicidade). Pesos relativos de
0 a 100, com soma positiva; não precisam somar 100. Peso zero desativa o componente.
Coberturas diferentes exigem atenção: uma nota alta com poucos componentes não
é garantia de uma tomada melhor. As notas são heurísticas, não probabilidades.

## Redundância e segurança

Compara somente a mesma viagem, grupo confirmado, movimento final, assunto e
tipo de mídia. Campos ausentes ou UNKNOWN não formam conjunto de comparação.
Thumbnails uniformes (desvio padrão abaixo de 5) não geram hash. Distância dHash
de até 8 em 64 bits sugere semelhança, nunca prova duplicação. O usuário confirma
visualmente. Não há agrupamento transitivo que declare todos os pares equivalentes.

Thumbnails são lidos exclusivamente do cache configurado, com limite de 10 MiB,
4 milhões de pixels, validação de caminho e hashes do original/derivada. O SRT usa
o leitor validado e cache da fase 3C. Nenhum frame é enviado a serviços externos.

## Jobs e auditoria

`CALCULATE_SCORE` usa o mecanismo persistente de jobs existente. O payload guarda
perfil, pesos, versão `scoring-v1`, início/fim, entradas, resultados e evidências.
Há progresso, erro sanitizado e recuperação após reinício. Resultados só são
publicados quando a viagem inteira termina; jobs anteriores continuam no banco.
Alterações no catálogo, classificação, pesos ou versão marcam resultados como
desatualizados. Mudanças no conteúdo do NAS/cache sem atualização do catálogo
só são detectadas ao recalcular. O ranking não depende de disponibilidade do NAS
se os dados locais necessários já existem.

API autenticada; toda escrita exige CSRF:

- `GET /api/editorial/score-profiles`
- `PUT /api/editorial/score-profiles/{instagram|youtube}` com `{"weights": {...}}`
- `POST /api/editorial/trips/{trip_id}/scores` com `{"profile": "instagram"}`
- `GET /api/editorial/trips/{trip_id}/scores?profile=instagram`
- `GET /api/editorial/score-jobs/{job_id}` para histórico/estado

Validação automatizada usa mídia sintética local, sem ffmpeg, NAS ou SD card.
Calibração com acervo real permanece necessária: um thumbnail não representa a
qualidade temporal inteira, composição ou intenção artística. Selects e exportação
pertencem às fases seguintes.

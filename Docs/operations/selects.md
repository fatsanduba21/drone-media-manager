# Selects automáticos — Fase 3F

No servidor Mac, configure `DMM_SELECTS_ROOT` para uma pasta **local gravável**,
fora do OMV e de diretórios sincronizados. Sem a variável, o padrão é `selects/`
ao lado do SQLite. Execute `uv run dmm-server migrate` (migração `0012_selects`)
e reinicie o servidor. O worker Windows não exporta os selects.

Em `/editorial/`, escolha uma viagem. Calcule o ranking se quiser sugestões
ordenadas; sem ele, todos os arquivos ainda podem ser revisados manualmente.
Abra **Selects para exportar**, clique **Gerar candidatos**, abra os previews
e escolha **Usar inteiro**, **Usar trecho**, **Salvar IN/OUT** em segundos, ou
**Rejeitar**. A regeneração preserva essas decisões. Trechos sugeridos vêm
da análise/revisão de movimento; a confirmação final é sempre humana.

Escolha `FAST` para copiar trechos sem recodificar (início pode variar com
keyframes) ou `ACCURATE` para recodificar vídeo em H.264/AAC. Arquivos inteiros
são copiados sem recodificação nos dois modos. Clique **Exportar confirmados**.
O servidor cria uma pasta nova `selects-<id>/`, contendo `SELECTS/`,
`selects_manifest.json` e `selects.csv`. O caminho aparece na tela quando o
job termina. É necessário `ffmpeg` instalado no servidor para trechos; a
exportação de arquivos inteiros dispensa ffmpeg.

O export lê exclusivamente os originais do OMV e confere SHA-256 antes e
depois. A pasta final só aparece após sucesso. Se o job falhar ou o servidor
reiniciar, revise disponibilidade, espaço e ffmpeg, depois solicite outra
exportação. Nunca edita nem remove originais. O manifesto registra arquivo,
hashes, limites, score e contexto de cada escolha.

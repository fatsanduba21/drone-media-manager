# Roteiro real de aceite pré-3C

Use uma **viagem de teste real** com pelo menos dois MP4, um SRT com GPS e um
asset sem GPS. Registre data, commit (`git rev-parse HEAD`), Windows/OMV/Mac,
nomes da viagem e do navegador. Não envie `.env`, senhas, chaves nem mídia.
Faça backup do SQLite antes de criar ou mover grupos: `uv run dmm-server backup`.

## 1. Windows → OMV → Mac

No Windows, com o OMV montado e `ffprobe` instalado, execute no mesmo checkout:

```powershell
uv run dmm-organize plan --source 'CAMINHO_ORIGEM' --trip 'VIAGEM_TESTE' --poi 'LOCAL' --output-omv 'RAIZ_OMV'
uv run dmm-organize apply --source 'CAMINHO_ORIGEM' --trip 'VIAGEM_TESTE' --poi 'LOCAL' --output-omv 'RAIZ_OMV'
```

Confira `errors=[]`, arquivos `CREATED`/`ALREADY_OK`, SRT pareado e o caminho do
`MANIFESTO.json`. Repita PLAN/APPLY com os mesmos argumentos; espere
`CREATED=0`. Confirme que os arquivos de origem não foram movidos/alterados.
No Mac, com `DMM_OMV_ROOT` apontando para a mesma raiz compartilhada:

```bash
uv run dmm-server migrate
uv run dmm-catalog preview "CAMINHO_MAC/MANIFESTO.json" --verify-hash
uv run dmm-catalog import "CAMINHO_MAC/MANIFESTO.json" --verify-hash
uv run dmm-derivatives generate --trip SLUG_DA_VIAGEM
```

Anote contagens de assets/arquivos disponíveis, conflitos e derivados com
falha. Repita `preview --verify-hash` após o aceite para provar que os
originais do OMV continuam iguais ao manifesto.

## 2. Galeria e 3A/3B

Na URL HTTPS com certificado válido, entre na galeria, confira a ordem dos
assets, thumbnail/proxy e seleção/download de um original. Abra `/editorial/`:

1. **Sugerir fronteiras:** confira ordem, SRT real, centro do intervalo e se
   as sugestões fazem sentido. Reprocessar não deve alterar grupos confirmados.
2. **Sugerir nomes próximos:** com GPS e chave Places, registre candidato
   coerente e confirme um nome. Sem GPS, crie outro grupo com nome manual.
3. Renomeie um grupo para um nome com acentos, por exemplo `Baía dos Porcos`.
   Faça **Adicionar seleção ao grupo** com outro intervalo e depois
   **Substituir membros do grupo**. Mova um asset entre grupos; confira que
   nenhum membro não selecionado desapareceu no modo adicionar.
4. Observe se ficou grupo com `0 arquivo(s)` após mover todos os membros e
   diga se ele deve continuar ou se precisa de exclusão antes da 3C.
5. Reinicie o serviço e recarregue `/editorial/`; confira nomes, Place ID
   confirmado e membros. Registre o comportamento sem chave Places ou quando
   o serviço Places falha, caso seja possível testá-lo sem interromper o uso.

Envie os relatórios JSON dos comandos, uma captura da galeria/editorial antes
e depois do restart, o resultado do `preview --verify-hash` final e uma lista
PASSA/FALHA/NÃO TESTADO para os itens acima. A 3B só será marcada **ACCEPTED**
quando as pendências relevantes estiverem verificadas.

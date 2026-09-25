# Movimento — Fase 3C

## Atualizar o Mac

Na pasta do projeto, com o `.env` já configurado:

```bash
uv run dmm-server backup
git switch main
git pull --ff-only origin main
uv sync --all-groups
uv run dmm-server migrate
```

Reinicie o processo do servidor. Se usa o LaunchAgent instalado:

```bash
launchctl kickstart -k gui/"$(id -u)"/com.drone-media-manager.server
```

Para execução em terminal, encerre a instância anterior e execute
`uv run dmm-server run`. A revisão esperada do SQLite é `0009_movement`.
A migração adiciona duas tabelas; preserva nomes, catálogo e grupos existentes.
Não move nem modifica originais, SRTs, thumbnails ou proxies.
Backup e rollback seguem [mac-server.md](mac-server.md#backup-and-rollback).

## Revisar

1. Abra `/editorial/` e selecione uma viagem.
2. **Sugerir movimentos** cria um job local persistente; acompanhe o progresso.
3. Selecione uma tomada. **Confirmar sugestão** salva a escolha humana;
   **Salvar movimento** aceita uma classe da lista ou texto manual.
4. Em **Trechos sugeridos e confirmados**, escolha **Revisar trecho**, ajuste
   início/fim em segundos e salve. Trechos sobrepostos são recusados. Para mudar
   limites de um trecho já confirmado, remova esse trecho e salve os novos
   limites. A remoção é auditada e não altera a mídia.
5. A classificação do arquivo inteiro e as classificações dos trechos são
   independentes. Apenas a classificação do arquivo alimenta os filtros e o
   nome editorial de download existentes.

Sugestões nunca alteram escolhas finais. Reprocessamentos preservam decisões,
mantêm histórico das análises e registram versão, confiança heurística e
evidência. A confiança não é uma medida de precisão validada.

## Sem SRT / sem internet

Nomes manuais e movimentos manuais funcionam normalmente para MP4/JPG sem SRT.
`UNKNOWN` é uma sugestão válida; campos ausentes não viram zero. Fotos não
recebem uma classificação de movimento automática. Trechos manuais exigem
duração conhecida no catálogo.

A classificação não usa APIs, modelos remotos ou ffmpeg. As amostras SRT são
armazenadas no SQLite local, com hash e versão do parser, e podem ser reutilizadas
com o NAS offline. O primeiro processamento precisa ler o SRT disponível e
verificar seu hash. Um SRT ausente, inválido, inseguro, maior que 8 MiB ou com
hash divergente resulta em UNKNOWN, sem bloquear a revisão. `HASH_MISMATCH`
e `UNVERIFIED` não reutilizam cache. Imagens e coordenadas não são enviadas
para serviços externos pela classificação.

Os nomes da 3B continuam opcionais: sugestões de Google dependem da configuração
e rede já existentes; ausência de chave/GPS/rede mantém o nome livre.

## Regras e limites

- Parser `srt-motion-v1`: tempo das legendas, latitude/longitude, altitude
  relativa, yaw, heading, gimbal pitch/yaw e velocidade quando presentes.
  Formatos/campos não reconhecidos ficam ausentes.
- `movement-v1`: órbitas exigem translação circular, estabilidade de raio e
  cobertura angular. Yaw sem translação é PAN, não órbita.
- Subida/descida usam deslocamento vertical. Foguete exige subida com câmera
  voltada para baixo e yaw estável. HOVER/ESTATICO exigem posição, altitude e
  orientação estáveis; ESTATICO usa altitude relativa próxima ao solo.
- Aproximação/afastamento exigem coordenadas de alvo confirmadas no painel
  **Referência**. O centroide do voo não é automaticamente considerado alvo.
  Alterar a referência requer nova análise para atualizar as sugestões.
- Travelling/sobrevoo exigem trajetória aproximadamente retilínea, heading
  coerente com GPS e orientação compatível. Dados insuficientes resultam em UNKNOWN.
- Segmentação inicial em janelas de 5 segundos, com consolidação e reavaliação
  de trechos; limites aproximados. Vídeos acima de 24 horas ficam UNKNOWN.
- Jobs executam no único servidor Mac, sem worker Windows. Reinício marca
  tarefas locais pendentes/em execução como INTERRUPTED; clique novamente em
  Sugerir movimentos para refazer. Resultados anteriores e decisões ficam salvos.
- Cada análise conserva suas amostras para auditoria; reprocessamentos repetidos
  aumentam o catálogo local. Não há purga automática de histórico.

## Dataset real e métricas

O aceite 9.5 ainda exige material real rotulado pelo operador. Testes sintéticos
não provam precisão em voo. Inclua órbita, pan estacionário, aproximação,
afastamento, foguete/subida, estático, ambiguidades e casos sem SRT.

Crie um JSON local (não versionar localização real ou mídia privada):

```json
[
  {"asset": "voo-01", "srt": "voo-01.SRT", "expected": "ORBITA"},
  {"asset": "voo-02", "srt": "voo-02.SRT", "expected": "PAN",
   "start_ms": 0, "end_ms": 10000},
  {"asset": "legado", "srt": null, "expected": "UNKNOWN"}
]
```

Caminhos SRT são relativos ao JSON; `anchor: [latitude, longitude]` pode informar
um alvo confiável para casos de aproximação/afastamento. Execute no Mac:

```bash
uv run python -m drone_media_manager.movement.evaluate /caminho/labels.json > /caminho/movement-report.json
```

O relatório inclui precision/recall por classe, suporte, UNKNOWN rate, versão e
resultado/evidência por caso. Denominadores sem casos retornam `null`, não 100%.
Registre também o aceite no Mac: confirmação, edição, trechos, reanálise,
reinício, nomes existentes, modo sem SRT/offline e hashes originais preservados.

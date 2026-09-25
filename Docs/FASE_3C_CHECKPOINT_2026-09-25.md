# Fase 3C — execução e aceite

Especificação e plano autorizados: seção 9 de
`03_FASE_3_INTELIGENCIA_EDITORIAL_E_ORGANIZACAO_AUTOMATICA.md`.
Escopo confirmado: movimento (3C), preservando nomes da 3B, modo legado e offline.
Base: `main` consolidada por fast-forward em `7099c6a`; registros de aceite
preexistentes preservados em commit. Publicação no main autorizada pela usuária.

## Roteiro de execução

- [x] Conservar amostras temporais SRT e testar regras conservadoras de movimento.
- [x] Persistir análises versionadas, segmentos e correções humanas auditadas;
      executar análise da viagem em job local persistente.
- [x] Integrar sugestão, evidência, confirmação e edição manual à triagem.
- [x] Revisão independente de código, com correção dos dois achados relevantes.
- [x] Validar suíte final e registrar implementação no main (`59a30be`).

## Decisões

- Reutilizar catálogo, autenticação/CSRF, auditoria e tabela de jobs existentes.
- Guardar amostras limitadas de SRT em SQLite local (JSON), sem dependência nova.
- Referência de aproximação/afastamento exige coordenada confirmada explicitamente;
  centroide da trajetória não é automaticamente um alvo confiável.
- Confiança é heurística, não precisão calibrada. Classes sem evidência ficam
  UNKNOWN; todas as classes iniciais continuam disponíveis para edição humana.
- Segmentação usa janelas de 5 segundos e consolida trechos adjacentes;
  limites sugeridos são aproximados e editáveis.
- Não há dataset real rotulado no repositório. Testes sintéticos não substituem
  o aceite real de precision/recall/UNKNOWN previsto na seção 9.5.

## Verificação

O primeiro uv tentou reconstruir o pacote e foi bloqueado pela
rede do sandbox (PyPI). As verificações usam a `.venv` existente com
`UV_NO_SYNC=1`, após `scripts/dev-env.ps1`, e o wrapper Windows de pytest.

Verificação final: **344 passed, 3 skipped**, cobertura total **90%**.
Comando: `scripts/pytest-windows.ps1 tests/unit tests/integration tests/security
--cov=drone_media_manager --cov-report=term-missing -q`.
Os três skips e avisos de depreciação já estavam presentes na base.

A revisão independente encontrou perda de movimentos lentos na segmentação e
uma disputa entre primeiras escritas da referência. Trechos contíguos agora são
reavaliados sem estender a classificação para telemetria ausente; PAN lento e
FOGUETE lento tiveram testes reproduzindo a falha antes da correção. A referência
usa a mesma transação SQLite serializada da confirmação de movimento.

No navegador integrado, com API simulada e dados sintéticos: confirmação da
sugestão, alteração manual, trecho de 2–8 segundos, reanálise, movimento manual
em foto sem SRT, fallback de nomes, criação e renomeação com acentos passaram.
Layout inspecionado visualmente. Autenticação, persistência, reprocessamento,
cache offline e APIs reais foram cobertos separadamente pelos testes Python.
Não foi executado aceite no Mac/OMV nesta sessão.

`ruff check .` e `mypy src` passaram. A formatação dos 16 arquivos Python
alterados passou; `ruff format --check .` registra 25 arquivos preexistentes
fora do escopo que seriam reformatados. A sintaxe JavaScript também tem teste
runnable com Node quando instalado.

## Aceite real pendente

Implementação disponível para validação, sem declarar a Fase 3C aceita em voo.
Faltam dataset real rotulado e precision/recall/UNKNOWN rate da seção 9.5.
O avaliador e o roteiro de atualização/aceite estão em
[operations/movement.md](operations/movement.md).

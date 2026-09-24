# Checkpoint da Fase 3B — nomes de Local / Grupo

**Data:** 24/09/2026

**Base:** `main` em `fb3258b`

**Estado:** concluída para uso e liberada para avançar à preparação da 3C.

## Aceite

- No Mac, após **Sugerir fronteiras** e selecionar um arquivo com GPS no SRT, **Sugerir nomes próximos** retornou candidatos reais, incluindo Praia do Bode e Barraca Recanto do Bode. A usuária confirmou que o fluxo funciona.
- O teste de integração cobre candidato escolhido, confirmação explícita, nome final e Place ID persistidos, edição manual posterior e criação com nome livre quando não há GPS/SRT. A indisponibilidade do Google não impede a organização manual.
- Antes da publicação de `fb3258b`, a suíte registrou 296 testes aprovados e 3 ignorados, com Ruff e mypy aprovados. O teste real no Mac comprovou a consulta de candidatos; a persistência após reinício do serviço não foi observada nessa sessão.

O procedimento está em [operations/location-names.md](operations/location-names.md). A melhoria da sequência de uso na interface fica para uma revisão futura, conforme decisão da usuária.

## Preparação da Fase 3C

A seção 9 de [03_FASE_3_INTELIGENCIA_EDITORIAL_E_ORGANIZACAO_AUTOMATICA.md](03_FASE_3_INTELIGENCIA_EDITORIAL_E_ORGANIZACAO_AUTOMATICA.md) define classificação de movimento por segmentos, com evidência, confiança e versão do algoritmo. O parser atual `grouping/telemetry.py` entrega apenas contagem, início, fim, centroide e horário; ele não conserva a trajetória por amostra nem extrai altitude, yaw ou gimbal. Esse é o primeiro requisito técnico a resolver para classificar movimentos com base em telemetria.

Antes de implementar o classificador, reunir e rotular vídeos reais de órbita, pan estacionário, aproximação, afastamento, foguete/subida, estático e casos ambíguos. Medir precisão, recall e taxa de `UNKNOWN`. Aproximação e afastamento exigem um referencial confiável; sem ele, usar `UNKNOWN`. Um vídeo pode conter mais de um segmento.

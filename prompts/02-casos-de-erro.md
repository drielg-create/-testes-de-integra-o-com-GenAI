# Prompt 2 — Casos de erro e falhas de comunicação

**Objetivo:** testar como o sistema se comporta quando a **comunicação** entre serviços falha (timeout, 5xx, resposta corrompida, falha no meio de uma compensação).
**Técnicas:** pedido direto (v1) → raciocínio guiado por taxonomia de falhas + restrições (v2).
**LLM usada:** Claude (Anthropic), em outubro de 2026.
**Resultado final:** `tests/test_02_casos_de_erro.py` (ER-01 a ER-10).

---

## v1 — pedido direto

```text
[mesmo CONTEXTO do prompt 1 v2]
Gere casos de teste de erro para o order-service.
```

**O que voltou (resumo):** casos de **validação de entrada** (`customer_id` vazio, `card_token` ausente, JSON inválido no corpo) e o 402 de cartão recusado.

**Problemas observados**
- "Erro" foi interpretado como **erro do cliente** (4xx de validação). Nenhum caso sobre o outro serviço cair.
- Esses casos já existiam no prompt 1, então quase tudo era repetido.

## v2 — taxonomia de falhas + perguntas explícitas (versão final)

```text
[CONTEXTO + INFRAESTRUTURA do prompt 1 v3]

Foque APENAS em falhas de COMUNICAÇÃO entre serviços, não em validação de entrada.

Para cada chamada externa do fluxo (GET /products, POST /reservations,
POST /charges, DELETE /reservations), considere estas categorias de falha:
  1. timeout       2. conexão recusada      3. HTTP 5xx
  4. 200 com corpo que não é JSON          5. 200 com JSON sem campo obrigatório

Antes de escrever o código, responda para cada combinação chamada x falha:
  a) qual status o order-service deve devolver?
  b) algum efeito colateral já aconteceu e precisa ser desfeito?
  c) há risco de cobrança duplicada?

Regras do sistema: timeout/5xx do upstream -> 503; resposta inválida -> 502;
o pagamento é retentado 1 vez em timeout/5xx com a MESMA Idempotency-Key;
402 (recusa) nunca é retentado.

Injete falhas com: system.inventory_spy.fail(method, path, action, times=1)
action = "timeout" | "connect_error" | <status int> | "<corpo cru>"
```

**O que melhorou**
- Pedir o raciocínio **(a)/(b)/(c) antes do código** gerou os casos mais valiosos da suíte:
  - **ER-04**: timeout no pagamento → retentativa com a **mesma chave** → **uma** cobrança só.
  - **ER-05**: pagamento falha duas vezes → reserva **liberada**, 503.
  - **ER-09**: a **compensação também falha** (DELETE da reserva dá timeout). A LLM perguntou "o que acontece com o estoque preso?". Isso me fez **mudar o código de produção** para marcar `compensation_pending = True` no pedido.
  - **ER-07**: recusa **não** é retentada. É um teste negativo da regra de retry.
- A matriz chamada × falha deu **diversidade sistemática** em vez de casos soltos. ER-01 é parametrizado com 4 tipos de falha.

**Ajustes manuais necessários**
- A LLM gerou as 20 combinações (4 chamadas × 5 falhas). Descartei as redundantes: o comportamento de "5xx" e "timeout" no GET de produto é o mesmo caminho de código, então ficou um teste parametrizado.
- Num caso ela assumiu que o order-service faria **retry no estoque** também, regra que não existe. Corrigi deixando a regra de retry explícita no prompt (trecho "Regras do sistema").

## Casos gerados (final)

| ID | Falha injetada | Esperado |
|----|----------------|----------|
| ER-01 | GET /products: timeout, conexão recusada, 500, 503 | 503, nenhuma cobrança |
| ER-02 | GET /products: corpo HTML | 502 |
| ER-03 | GET /products: JSON sem `price_cents` | 502 |
| ER-04 | POST /charges: 1 timeout | retentativa com mesma chave, 201, 1 cobrança |
| ER-05 | POST /charges: 2 timeouts | 503, reserva liberada, 0 cobranças |
| ER-06 | POST /charges: 1× 500 | retentativa, 201 |
| ER-07 | cartão recusado | 402, **sem** retentativa |
| ER-08 | POST /charges: JSON sem `charge_id` | 502, estoque devolvido |
| ER-09 | DELETE /reservations (compensação): timeout | 402, pedido com `compensation_pending` |
| ER-10 | POST /reservations: timeout | 503, nenhuma cobrança |

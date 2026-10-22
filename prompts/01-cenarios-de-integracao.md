# Prompt 1 — Geração de cenários de integração (+ dados de teste)

**Objetivo:** obter cenários que exercitem o fluxo *entre* os serviços (Pedidos → Estoque → Pagamentos), não só o endpoint isolado.
**Técnicas:** zero-shot (v1) → contexto + persona + formato de saída (v2) → few-shot + valores-limite (v3).
**LLM usada:** Claude (Anthropic), em outubro de 2026.
**Resultado final:** `tests/test_01_cenarios_integracao.py` (CI-01 a CI-17).

---

## v1 — zero-shot

```text
Gere casos de teste de integração para uma API de pedidos de e-commerce.
```

**O que voltou (resumo):** ~8 casos genéricos, do tipo "criar pedido válido → 201", "pedido sem itens → 400", "buscar pedido inexistente → 404".

**Problemas observados**
- Testes de **endpoint isolado**, não de integração: nenhum caso olhou o estoque ou o pagamento.
- Endpoints e campos **inventados** (`/api/v1/order`, `quantity`, `price` em reais com float).
- Só caminho feliz e validação de entrada. Nada sobre o que acontece *entre* os serviços.
- Código em Postman/JavaScript, outra stack.

## v2 — contexto, persona e formato

```text
Você é um engenheiro de QA sênior especializado em microsserviços.

CONTEXTO
Sistema com 3 serviços REST:
- order-service (consumer), POST /orders {customer_id, items:[{sku, qty}], card_token}
- inventory-service: GET /products/{sku} -> {sku, price_cents, stock};
  POST /reservations; POST /reservations/{id}/confirm; DELETE /reservations/{id}
- payment-service: POST /charges (header Idempotency-Key) -> 201 {charge_id, status}; 402 se recusado

Fluxo do POST /orders: busca preços -> reserva estoque -> cobra -> confirma reserva.
Se a cobrança falha, a reserva é liberada (compensação).

TAREFA
Liste cenários de INTEGRAÇÃO. Para cada um, diga o efeito esperado em CADA serviço
(resposta do order-service, estoque, cobranças, estado da reserva).

FORMATO
Tabela: ID | cenário | pré-condição | ação | resultado esperado (por serviço).
Depois, código pytest usando FastAPI TestClient.
```

**O que melhorou**
- Os cenários passaram a verificar **efeitos colaterais nos outros serviços**: "estoque insuficiente → 409 **e nenhuma cobrança feita**", "cartão recusado → 402 **e estoque devolvido**".
- Apareceram cenários que eu não tinha pensado: **ordem das chamadas** (CI-04) e **Idempotency-Key = order_id** (CI-03).
- Endpoints e campos corretos, porque estavam no contexto.

**Problemas que ficaram**
- O código criava os serviços com `unittest.mock.patch` em `httpx.Client.request`. Assim os providers reais nunca rodavam e o teste virava teste unitário disfarçado.
- Pouca variação de dados: sempre `qty: 1` ou `qty: 2`.

## v3 — few-shot + infraestrutura existente + valores-limite (versão final)

Acrescentei ao prompt v2:

```text
INFRAESTRUTURA (use, não crie mocks):
A fixture `system` sobe os 3 serviços reais em memória. Ela expõe:
  system.client (TestClient do order-service), system.stock(sku),
  system.charges, system.reservation_statuses(),
  system.inventory_spy / system.payment_spy (.calls(method, path), .requests)

EXEMPLO DO ESTILO ESPERADO:
def test_estoque_insuficiente_nao_gera_cobranca(system, order_payload):
    resp = system.client.post("/orders", json=order_payload(items=[{"sku": "SKU-CANECA", "qty": 4}]))
    assert resp.status_code == 409
    assert system.payment_spy.requests == []
    assert system.stock("SKU-CANECA") == 3

DADOS DE TESTE:
Estoque inicial: SKU-CAMISETA (4990, 10 un), SKU-CANECA (2950, 3 un), SKU-ULTIMA (15000, 1 un).
Limite: 1 <= qty <= 100. Gere também uma tabela parametrizada de VALORES-LIMITE
(abaixo, no limite, acima) e cenários de CONCORRÊNCIA pela última unidade.
Não invente endpoints nem campos fora do contexto.
```

**O que melhorou**
- O código saiu **executável sem ajustes** nos testes de cenário (CI-01 a CI-10).
- A tabela de **valores-limite** (CI-11 a CI-17) cobre `0`, `-1`, `101`, `sku vazio`, "exatamente o estoque" (10) e "estoque + 1" (11). Os dois últimos são limites de integração, porque dependem do estado do outro serviço.
- Cenários **dependentes de estado** entre pedidos: "dois pedidos pela última unidade" (CI-09) e "item de pedido recusado volta a ficar disponível" (CI-10).
- A LLM sugeriu, sem eu pedir, verificar que pedidos inválidos (422) **não chamam nenhum serviço externo**.

**Ajuste manual necessário:** na v3 a LLM propôs um teste de "dois pedidos simultâneos" com `threading`. Ele era não determinístico com os serviços em memória, então troquei por dois pedidos sequenciais (CI-09). A garantia de atomicidade fica no provider.

## Casos gerados (final)

| ID | Cenário | Verifica em |
|----|---------|-------------|
| CI-01 | Pedido de 1 item confirmado, estoque debitado | pedidos, estoque, pagamento |
| CI-02 | Total de vários itens usa os preços do estoque | pedidos, pagamento |
| CI-03 | Cobrança usa `order_id` como Idempotency-Key | pagamento |
| CI-04 | Ordem: preço → reserva → (cobrança) → confirmação | estoque |
| CI-05 | Pedido criado pode ser consultado | pedidos |
| CI-06 | Estoque insuficiente → 409, sem cobrança | estoque, pagamento |
| CI-07 | Cartão recusado → 402, reserva liberada | todos |
| CI-08 | SKU inexistente → 422, sem reserva | estoque |
| CI-09 | Dois pedidos pela última unidade → 201 + 409 | estoque, pagamento |
| CI-10 | Item de pedido recusado volta a ficar disponível | estoque |
| CI-11..17 | Valores-limite de quantidade/itens | pedidos, estoque |

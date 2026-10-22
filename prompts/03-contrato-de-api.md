# Prompt 3 — Contrato de API (consumer-driven)

**Objetivo:** garantir que os *providers* (Estoque, Pagamentos) continuem entregando exatamente o que o *consumer* (Pedidos) usa, e detectar quebras de contrato antes da integração em produção.
**Técnicas:** extração a partir do código (v1) → "o que o consumer realmente lê" + exemplos de resposta (v2).
**LLM usada:** Claude (Anthropic), em outubro de 2026.
**Resultado final:** `tests/test_03_contrato_api.py` (CT-01 a CT-10).

---

## v1 — gerar contrato a partir do provider

```text
Aqui está o código do inventory-service e do payment-service: [código colado].
Gere testes de contrato para essas APIs.
```

**O que voltou (resumo):** testes que validavam **todos** os campos de todas as respostas (`name`, `stock`, `items[].sku`...) e um esquema OpenAPI completo.

**Problemas observados**
- Contrato **centrado no provider**: se o Estoque mudar `name` (que o Pedidos nem usa), o teste quebra. É um falso positivo.
- Faltaram exatamente os pontos que o consumer depende: o **tipo** de `price_cents` (inteiro, não float) e o comportamento de **idempotência**.

## v2 — consumer-driven (versão final)

```text
Você vai escrever testes de contrato CONSUMER-DRIVEN (estilo Pact, mas em pytest).

Este é o código do CONSUMER (order-service): [order_service.py colado]

Passo 1: liste cada campo, status HTTP e header que o consumer LÊ ou ENVIA
         em cada chamada aos providers. Ignore o que ele não usa.
Passo 2: para cada item, escreva um teste que rode direto contra o PROVIDER
         (create_inventory_app() / create_payment_app() com TestClient)
         e verifique presença E tipo do campo.
Passo 3: inclua os contratos de COMPORTAMENTO que o consumer assume
         (ex.: Idempotency-Key repetida não cobra de novo).

Exemplo de resposta real do provider:
GET /products/SKU-CAMISETA -> {"sku":"SKU-CAMISETA","name":"Camiseta","price_cents":4990,"stock":10}
```

**O que melhorou**
- Ao listar "o que o consumer lê" (passo 1), a LLM encontrou dependências implícitas:
  - `price_cents` precisa ser **int** (o total é calculado em centavos) → CT-01
  - o consumer distingue **404** de produto (→ 422) e **409** de reserva (→ 409) → CT-02, CT-04
  - o consumer **assume** idempotência no retry → CT-07 e CT-08 (contrato de comportamento, não só de formato)
- Os testes ficaram **menores e mais estáveis**: campos que o consumer não usa não são verificados.

**Ajuste manual necessário:** a LLM sugeriu usar a biblioteca `pact-python` com broker. Para o tamanho deste exercício mantive pytest puro, com a mesma ideia (o consumer define, o provider verifica).

## Casos gerados (final)

| ID | Provider | Contrato |
|----|----------|----------|
| CT-01 | inventory | `GET /products/{sku}` → `price_cents: int`, JSON |
| CT-02 | inventory | SKU inexistente → 404 `PRODUCT_NOT_FOUND` |
| CT-03 | inventory | `POST /reservations` → 201 `{id, status: held}` |
| CT-04 | inventory | sem estoque → 409 `OUT_OF_STOCK` |
| CT-05 | inventory | confirmar / liberar reserva → 200 |
| CT-06 | payment | `POST /charges` → 201 `{charge_id, status, amount_cents}` |
| CT-07 | payment | sem `Idempotency-Key` → 400 |
| CT-08 | payment | chave repetida → mesma cobrança (200) |
| CT-09 | payment | cartão recusado → 402 `CARD_DECLINED` |
| CT-10 | payment | valor ≤ 0 → 422 |

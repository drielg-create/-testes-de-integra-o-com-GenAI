# GenAI como copiloto de testes de integração

Atividade do fórum da **Unidade III**: tipos de prompt para apoiar **testes de integração** entre serviços REST, com os casos de teste gerados por uma LLM registrados e executáveis.

## Cenário

Um checkout de e-commerce com **três serviços REST** que conversam por HTTP:

```
             GET /products/{sku}         ┌───────────────────┐
           ┌───────────────────────────▶│ inventory-service │
           │ POST /reservations          │  (estoque)        │
┌──────────┴──────┐ POST .../confirm     └───────────────────┘
│  order-service  │ DELETE /reservations/{id}  ← compensação
│  (pedidos)      │
└──────────┬──────┘                      ┌───────────────────┐
           │ POST /charges               │  payment-service  │
           └───────────────────────────▶│  (pagamentos)     │
             Idempotency-Key: order_id   └───────────────────┘
```

Fluxo do `POST /orders`: **busca preços → reserva estoque → cobra (1 retentativa) → confirma reserva**. Se a cobrança falha, a reserva é **liberada** (padrão saga/compensação).

## Tipos de prompt usados

| # | Tipo de prompt | Técnica final | Arquivo do prompt | Testes gerados |
|---|----------------|---------------|-------------------|----------------|
| 1 | **Cenários de integração + dados de teste** | contexto + persona + few-shot + valores-limite | [prompts/01](prompts/01-cenarios-de-integracao.md) | [17 casos](tests/test_01_cenarios_integracao.py) |
| 2 | **Casos de erro / falhas de comunicação** | taxonomia de falhas + raciocínio antes do código | [prompts/02](prompts/02-casos-de-erro.md) | [13 casos](tests/test_02_casos_de_erro.py) |
| 3 | **Contrato de API (consumer-driven)** | "liste o que o consumer usa" → teste no provider | [prompts/03](prompts/03-contrato-de-api.md) | [12 casos](tests/test_03_contrato_api.py) |

Cada arquivo em `prompts/` mostra **todas as versões** do prompt (v1 → final), o que a LLM devolveu, os problemas encontrados e os ajustes feitos.

## Como rodar

```bash
pip install -r requirements.txt
pytest -v
```

Os três serviços sobem **em memória** (FastAPI `TestClient`). As chamadas entre eles passam por um `SpyTransport` (`tests/conftest.py`) que registra as requisições e permite **injetar falhas** (timeout, conexão recusada, 5xx, JSON inválido) sem mocks no código de produção.

## Os testes detectam bugs de verdade? (teste de mutação)

Para medir a qualidade dos casos gerados, introduzi bugs propositalmente e vi qual suíte os detectava:

| Mutação (bug introduzido) | Prompt 1 cenários | Prompt 2 erros | Prompt 3 contrato |
|---------------------------|:-:|:-:|:-:|
| M1 — remover a retentativa do pagamento | — | ✅ 2 falhas | — |
| M2 — Idempotency-Key aleatória em vez do `order_id` | ✅ 1 | — | — |
| M3 — remover a compensação (não libera reserva) | ✅ 2 | ✅ 3 | — |
| M4 — total ignora a quantidade | ✅ 2 | — | — |
| M5 — 5xx do upstream não tratado | — | ✅ 3 | — |
| M6 — *provider* aceita cobrança sem Idempotency-Key | — | — | ✅ 1 |
| M7 — *provider* renomeia `price_cents` → `price` | ✅ 11 | ✅ 6 | ✅ 1 (aponta o campo) |

**Leitura:** nenhum tipo de prompt sozinho pegou todos os bugs, e as suítes **se complementam**. Os cenários pegam erros de regra de negócio, os casos de erro pegam falhas de resiliência e o contrato pega mudanças no provider (M6 só foi detectado por ele). Em M7, as suítes 1 e 2 quebram em 17 testes com mensagens genéricas; o contrato quebra em **um** teste que diz exatamente `campo obrigatório ausente: price_cents`.

## Estrutura

```
app/
  order_service.py       # consumer: orquestra estoque + pagamento
  inventory_service.py   # provider: produtos e reservas
  payment_service.py     # provider: cobranças idempotentes
prompts/                 # os prompts, versão a versão, com análise
tests/
  conftest.py            # sobe os 3 serviços conectados + injeção de falhas
  test_01_cenarios_integracao.py
  test_02_casos_de_erro.py
  test_03_contrato_api.py
docs/forum-post.md       # texto da postagem no fórum
```

## Sobre o uso de GenAI

Os prompts foram executados no **Claude (Anthropic)**. Os casos de teste são a saída da versão final de cada prompt. Revisei todos e ajustei alguns à mão; os ajustes estão anotados em cada arquivo de `prompts/`. O código dos serviços é um sistema didático criado para o exercício.

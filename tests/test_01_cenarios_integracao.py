"""Casos gerados pelo PROMPT 1 — Cenários de integração (versão final, v3).

Ver prompts/01-cenarios-de-integracao.md. Cada teste valida o efeito
COMBINADO nos três serviços (resposta + estoque + cobranças + reservas).
"""
import pytest

from tests.conftest import System, body_of


# CI-01
def test_pedido_com_um_item_e_confirmado_e_estoque_debitado(system, order_payload):
    resp = system.client.post("/orders", json=order_payload())

    assert resp.status_code == 201
    order = resp.json()
    assert order["status"] == "confirmed"
    assert order["total_cents"] == 2 * 4990
    assert system.stock("SKU-CAMISETA") == 8
    assert system.reservation_statuses() == ["confirmed"]
    assert len(system.charges) == 1


# CI-02
def test_total_de_varios_itens_e_calculado_com_precos_do_estoque(system, order_payload):
    items = [{"sku": "SKU-CAMISETA", "qty": 1}, {"sku": "SKU-CANECA", "qty": 3}]
    resp = system.client.post("/orders", json=order_payload(items=items))

    assert resp.status_code == 201
    assert resp.json()["total_cents"] == 4990 + 3 * 2950
    assert system.charges[0]["amount_cents"] == 4990 + 3 * 2950


# CI-03
def test_cobranca_usa_order_id_como_idempotency_key(system, order_payload):
    order = system.client.post("/orders", json=order_payload()).json()

    [charge_request] = system.payment_spy.calls("POST", "/charges")
    assert charge_request.headers["Idempotency-Key"] == order["id"]
    assert body_of(charge_request)["order_id"] == order["id"]


# CI-04
def test_ordem_das_chamadas_entre_servicos(system, order_payload):
    system.client.post("/orders", json=order_payload())

    inventory_calls = [(r.method, r.url.path) for r in system.inventory_spy.requests]
    assert inventory_calls[0] == ("GET", "/products/SKU-CAMISETA")
    assert inventory_calls[1] == ("POST", "/reservations")
    assert inventory_calls[2][0] == "POST" and inventory_calls[2][1].endswith("/confirm")


# CI-05
def test_pedido_criado_pode_ser_consultado(system, order_payload):
    created = system.client.post("/orders", json=order_payload()).json()

    resp = system.client.get(f"/orders/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["charge_id"] == created["charge_id"]


# CI-06
def test_estoque_insuficiente_nao_gera_cobranca(system, order_payload):
    resp = system.client.post("/orders", json=order_payload(items=[{"sku": "SKU-CANECA", "qty": 4}]))

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "OUT_OF_STOCK"
    assert system.payment_spy.requests == []
    assert system.stock("SKU-CANECA") == 3


# CI-07
def test_pagamento_recusado_libera_reserva(system, order_payload):
    resp = system.client.post("/orders", json=order_payload(card_token="tok_declined"))

    assert resp.status_code == 402
    assert system.stock("SKU-CAMISETA") == 10
    assert system.reservation_statuses() == ["released"]
    order_id = resp.json()["detail"]["order_id"]
    assert system.client.get(f"/orders/{order_id}").json()["status"] == "failed"


# CI-08
def test_produto_inexistente_nao_cria_reserva(system, order_payload):
    resp = system.client.post("/orders", json=order_payload(items=[{"sku": "SKU-FANTASMA", "qty": 1}]))

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "PRODUCT_NOT_FOUND"
    assert system.inventory_spy.calls("POST", "/reservations") == []


# CI-09
def test_dois_pedidos_pela_ultima_unidade_so_um_e_confirmado(system, order_payload):
    payload = order_payload(items=[{"sku": "SKU-ULTIMA", "qty": 1}])

    first = system.client.post("/orders", json=payload)
    second = system.client.post("/orders", json=payload)

    assert (first.status_code, second.status_code) == (201, 409)
    assert system.stock("SKU-ULTIMA") == 0
    assert len(system.charges) == 1


# CI-10
def test_item_de_pedido_mal_sucedido_volta_a_ficar_disponivel(system, order_payload):
    payload = order_payload(items=[{"sku": "SKU-ULTIMA", "qty": 1}])
    declined = system.client.post("/orders", json={**payload, "card_token": "tok_declined"})
    retry = system.client.post("/orders", json=payload)

    assert (declined.status_code, retry.status_code) == (402, 201)


# Dados de teste (CI-11..CI-17): valores-limite gerados na v3 do prompt.
@pytest.mark.parametrize(
    "items, expected_status",
    [
        pytest.param([], 422, id="CI-11 lista de itens vazia"),
        pytest.param([{"sku": "SKU-CAMISETA", "qty": 0}], 422, id="CI-12 quantidade zero"),
        pytest.param([{"sku": "SKU-CAMISETA", "qty": -1}], 422, id="CI-13 quantidade negativa"),
        pytest.param([{"sku": "SKU-CAMISETA", "qty": 101}], 422, id="CI-14 acima do maximo por item"),
        pytest.param([{"sku": "", "qty": 1}], 422, id="CI-15 sku vazio"),
        pytest.param([{"sku": "SKU-CAMISETA", "qty": 10}], 201, id="CI-16 exatamente o estoque"),
        pytest.param([{"sku": "SKU-CAMISETA", "qty": 11}], 409, id="CI-17 estoque mais um"),
    ],
)
def test_valores_limite_de_quantidade(order_payload, items, expected_status):
    system = System()
    resp = system.client.post("/orders", json=order_payload(items=items))

    assert resp.status_code == expected_status
    if expected_status == 422:
        # validação acontece ANTES de qualquer chamada externa
        assert system.inventory_spy.requests == []

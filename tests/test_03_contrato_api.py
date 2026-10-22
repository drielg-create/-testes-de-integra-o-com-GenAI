"""Casos gerados pelo PROMPT 3 — Contrato de API consumer-driven (v2).

Ver prompts/03-contrato-de-api.md. Os testes verificam, direto nos providers
(Estoque e Pagamentos), que eles entregam o que o consumer (Pedidos) usa.
Se um provider renomear/remover um campo, este arquivo quebra antes da produção.
"""
import pytest
from fastapi.testclient import TestClient

from app.inventory_service import create_inventory_app
from app.payment_service import create_payment_app


@pytest.fixture
def inventory():
    return TestClient(create_inventory_app())


@pytest.fixture
def payment():
    return TestClient(create_payment_app())


def assert_types(body: dict, schema: dict):
    for field, expected_type in schema.items():
        assert field in body, f"campo obrigatório ausente: {field}"
        assert isinstance(body[field], expected_type), f"{field}: esperado {expected_type}"


# CT-01
def test_get_product_entrega_price_cents_inteiro(inventory):
    resp = inventory.get("/products/SKU-CAMISETA")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert_types(resp.json(), {"sku": str, "price_cents": int, "stock": int})


# CT-02
def test_get_product_inexistente_retorna_404(inventory):
    resp = inventory.get("/products/NAO-EXISTE")

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "PRODUCT_NOT_FOUND"


# CT-03
def test_post_reservations_retorna_201_com_id(inventory):
    resp = inventory.post("/reservations", json={"items": [{"sku": "SKU-CAMISETA", "qty": 1}]})

    assert resp.status_code == 201
    assert_types(resp.json(), {"id": str, "status": str})
    assert resp.json()["status"] == "held"


# CT-04
def test_post_reservations_sem_estoque_retorna_409_com_codigo(inventory):
    resp = inventory.post("/reservations", json={"items": [{"sku": "SKU-CANECA", "qty": 99}]})

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "OUT_OF_STOCK"


# CT-05
@pytest.mark.parametrize("action, method, expected", [
    ("confirm", "POST", "confirmed"),
    ("release", "DELETE", "released"),
])
def test_confirmar_e_liberar_reserva(inventory, action, method, expected):
    reservation_id = inventory.post(
        "/reservations", json={"items": [{"sku": "SKU-CAMISETA", "qty": 1}]}
    ).json()["id"]
    url = f"/reservations/{reservation_id}" + ("/confirm" if action == "confirm" else "")

    resp = inventory.request(method, url)

    assert resp.status_code == 200
    assert resp.json()["status"] == expected


# CT-06
def test_post_charges_aprovado_entrega_charge_id(payment):
    resp = payment.post(
        "/charges",
        json={"amount_cents": 1000, "card_token": "tok_ok", "order_id": "ord_1"},
        headers={"Idempotency-Key": "ord_1"},
    )

    assert resp.status_code == 201
    assert_types(resp.json(), {"charge_id": str, "status": str, "amount_cents": int})


# CT-07
def test_post_charges_exige_idempotency_key(payment):
    resp = payment.post(
        "/charges", json={"amount_cents": 1000, "card_token": "tok_ok", "order_id": "ord_1"}
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


# CT-08
def test_post_charges_repetido_devolve_mesma_cobranca(payment):
    request = dict(
        json={"amount_cents": 1000, "card_token": "tok_ok", "order_id": "ord_1"},
        headers={"Idempotency-Key": "ord_1"},
    )
    first = payment.post("/charges", **request)
    second = payment.post("/charges", **request)

    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["charge_id"] == second.json()["charge_id"]


# CT-09
def test_cartao_recusado_retorna_402(payment):
    resp = payment.post(
        "/charges",
        json={"amount_cents": 1000, "card_token": "tok_declined", "order_id": "ord_1"},
        headers={"Idempotency-Key": "ord_1"},
    )

    assert resp.status_code == 402
    assert resp.json()["detail"]["code"] == "CARD_DECLINED"


# CT-10
@pytest.mark.parametrize("amount", [0, -100])
def test_valor_nao_positivo_e_rejeitado(payment, amount):
    resp = payment.post(
        "/charges",
        json={"amount_cents": amount, "card_token": "tok_ok", "order_id": "ord_1"},
        headers={"Idempotency-Key": "ord_1"},
    )

    assert resp.status_code == 422

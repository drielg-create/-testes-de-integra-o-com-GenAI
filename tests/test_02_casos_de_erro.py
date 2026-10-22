"""Casos gerados pelo PROMPT 2 — Casos de erro e falhas de comunicação (v2).

Ver prompts/02-casos-de-erro.md. As falhas são injetadas na camada de
transporte HTTP (SpyTransport), simulando rede/serviço degradado.
"""
import pytest


# ER-01
@pytest.mark.parametrize("action", ["timeout", "connect_error", 500, 503])
def test_estoque_indisponivel_retorna_503_sem_cobrar(system, order_payload, action):
    system.inventory_spy.fail("GET", "/products", action)

    resp = system.client.post("/orders", json=order_payload())

    assert resp.status_code == 503
    assert system.payment_spy.requests == []


# ER-02
def test_resposta_malformada_do_estoque_retorna_502(system, order_payload):
    system.inventory_spy.fail("GET", "/products", "<html>Bad Gateway</html>")

    resp = system.client.post("/orders", json=order_payload())

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "UPSTREAM_INVALID_RESPONSE"


# ER-03
def test_resposta_do_estoque_sem_campo_obrigatorio_retorna_502(system, order_payload):
    system.inventory_spy.fail("GET", "/products", '{"sku": "SKU-CAMISETA"}')

    resp = system.client.post("/orders", json=order_payload())

    assert resp.status_code == 502


# ER-04
def test_timeout_no_pagamento_e_retentado_com_mesma_chave_e_cobra_uma_vez(system, order_payload):
    system.payment_spy.fail("POST", "/charges", "timeout", times=1)

    resp = system.client.post("/orders", json=order_payload())

    assert resp.status_code == 201
    attempts = system.payment_spy.calls("POST", "/charges")
    assert len(attempts) == 2
    assert attempts[0].headers["Idempotency-Key"] == attempts[1].headers["Idempotency-Key"]
    assert len(system.charges) == 1


# ER-05
def test_pagamento_falha_duas_vezes_libera_reserva_e_retorna_503(system, order_payload):
    system.payment_spy.fail("POST", "/charges", "timeout", times=2)

    resp = system.client.post("/orders", json=order_payload())

    assert resp.status_code == 503
    assert system.stock("SKU-CAMISETA") == 10
    assert system.reservation_statuses() == ["released"]
    assert system.charges == []


# ER-06
def test_erro_500_no_pagamento_tambem_e_retentado(system, order_payload):
    system.payment_spy.fail("POST", "/charges", 500, times=1)

    resp = system.client.post("/orders", json=order_payload())

    assert resp.status_code == 201
    assert len(system.payment_spy.calls("POST", "/charges")) == 2


# ER-07
def test_recusa_do_cartao_nao_e_retentada(system, order_payload):
    resp = system.client.post("/orders", json=order_payload(card_token="tok_declined"))

    assert resp.status_code == 402
    assert len(system.payment_spy.calls("POST", "/charges")) == 1


# ER-08
def test_resposta_de_pagamento_sem_charge_id_libera_reserva(system, order_payload):
    system.payment_spy.fail("POST", "/charges", '{"status": "approved"}')

    resp = system.client.post("/orders", json=order_payload())

    assert resp.status_code == 502
    assert system.stock("SKU-CAMISETA") == 10


# ER-09
def test_falha_na_compensacao_marca_pedido_para_reprocessamento(system, order_payload):
    system.inventory_spy.fail("DELETE", "/reservations", "timeout")

    resp = system.client.post("/orders", json=order_payload(card_token="tok_declined"))

    assert resp.status_code == 402
    order = system.client.get(f"/orders/{resp.json()['detail']['order_id']}").json()
    assert order["status"] == "failed"
    assert order["compensation_pending"] is True


# ER-10
def test_estoque_cai_ao_reservar_nao_cobra(system, order_payload):
    system.inventory_spy.fail("POST", "/reservations", "timeout")

    resp = system.client.post("/orders", json=order_payload())

    assert resp.status_code == 503
    assert system.payment_spy.requests == []

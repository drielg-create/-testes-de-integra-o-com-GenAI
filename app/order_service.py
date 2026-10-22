"""Serviço de Pedidos (consumer) — orquestra Estoque e Pagamentos.

Fluxo de POST /orders:
  1. GET  inventory /products/{sku}          -> preço de cada item
  2. POST inventory /reservations            -> reserva o estoque
  3. POST payment   /charges                 -> cobra (Idempotency-Key = order_id,
                                                1 retentativa em timeout/5xx)
  4a. sucesso: POST inventory /reservations/{id}/confirm
  4b. falha:   DELETE inventory /reservations/{id}   (compensação)
"""
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MAX_QTY_PER_ITEM = 100


class OrderItem(BaseModel):
    sku: str = Field(min_length=1)
    qty: int = Field(ge=1, le=MAX_QTY_PER_ITEM)


class OrderRequest(BaseModel):
    customer_id: str = Field(min_length=1)
    items: list[OrderItem] = Field(min_length=1)
    card_token: str = Field(min_length=1)


class UpstreamError(Exception):
    def __init__(self, status_code: int, code: str):
        self.status_code = status_code
        self.code = code


def create_order_app(inventory: httpx.Client, payment: httpx.Client) -> FastAPI:
    app = FastAPI(title="order-service")
    app.state.orders = {}

    def call(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
        """Chama um serviço externo e traduz falhas de infraestrutura."""
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TimeoutException:
            raise UpstreamError(503, "UPSTREAM_TIMEOUT")
        except httpx.TransportError:
            raise UpstreamError(503, "UPSTREAM_UNAVAILABLE")
        if response.status_code >= 500:
            raise UpstreamError(503, "UPSTREAM_ERROR")
        return response

    def json_body(response: httpx.Response, *required: str) -> dict:
        try:
            body = response.json()
        except ValueError:
            raise UpstreamError(502, "UPSTREAM_INVALID_RESPONSE")
        if not isinstance(body, dict) or any(field not in body for field in required):
            raise UpstreamError(502, "UPSTREAM_INVALID_RESPONSE")
        return body

    def charge(order_id: str, amount_cents: int, card_token: str) -> httpx.Response:
        payload = {"amount_cents": amount_cents, "card_token": card_token, "order_id": order_id}
        headers = {"Idempotency-Key": order_id}
        try:
            return call(payment, "POST", "/charges", json=payload, headers=headers)
        except UpstreamError as first_error:
            if first_error.status_code != 503:
                raise
            # A mesma Idempotency-Key garante que a retentativa não cobra duas vezes.
            return call(payment, "POST", "/charges", json=payload, headers=headers)

    def fail(order: dict, status_code: int, code: str):
        order["status"] = "failed"
        order["error"] = code
        raise HTTPException(status_code, detail={"code": code, "order_id": order["id"]})

    @app.post("/orders", status_code=201)
    def create_order(req: OrderRequest):
        order_id = f"ord_{uuid.uuid4().hex[:12]}"
        order = {"id": order_id, "customer_id": req.customer_id, "status": "pending"}
        app.state.orders[order_id] = order

        # 1. preços
        try:
            total_cents = 0
            for item in req.items:
                response = call(inventory, "GET", f"/products/{item.sku}")
                if response.status_code == 404:
                    fail(order, 422, "PRODUCT_NOT_FOUND")
                product = json_body(response, "price_cents")
                total_cents += product["price_cents"] * item.qty

            # 2. reserva
            response = call(
                inventory, "POST", "/reservations",
                json={"items": [i.model_dump() for i in req.items]},
            )
            if response.status_code == 409:
                fail(order, 409, "OUT_OF_STOCK")
            reservation_id = json_body(response, "id")["id"]
        except UpstreamError as err:
            fail(order, err.status_code, err.code)

        order.update(total_cents=total_cents, reservation_id=reservation_id)

        # 3. pagamento (com compensação em caso de falha)
        try:
            response = charge(order_id, total_cents, req.card_token)
            if response.status_code == 402:
                raise UpstreamError(402, "PAYMENT_DECLINED")
            charge_id = json_body(response, "charge_id", "status")["charge_id"]
        except UpstreamError as err:
            try:
                call(inventory, "DELETE", f"/reservations/{reservation_id}")
            except UpstreamError:
                order["compensation_pending"] = True
            fail(order, err.status_code, err.code)

        # 4. confirmação
        call(inventory, "POST", f"/reservations/{reservation_id}/confirm")
        order.update(status="confirmed", charge_id=charge_id)
        return order

    @app.get("/orders/{order_id}")
    def get_order(order_id: str):
        order = app.state.orders.get(order_id)
        if order is None:
            raise HTTPException(404, detail={"code": "ORDER_NOT_FOUND"})
        return order

    return app

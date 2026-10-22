"""Infraestrutura de teste: sobe os 3 serviços em memória e liga uns aos outros.

Cada chamada do Serviço de Pedidos para Estoque/Pagamentos passa por um
`SpyTransport`, que (a) registra a requisição e (b) permite injetar falhas
(timeout, 5xx, JSON inválido) sem mocks no código de produção.
"""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.inventory_service import create_inventory_app
from app.order_service import create_order_app
from app.payment_service import create_payment_app


class SpyTransport(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport):
        self.inner = inner
        self.requests: list[httpx.Request] = []
        self._faults: list[dict] = []

    def fail(self, method: str, path: str, action, times: int = 1):
        """Faz as próximas `times` chamadas `method path` falharem com `action`.

        action: "timeout" | "connect_error" | int (status HTTP) | str (corpo cru 200)
        """
        self._faults.append({"method": method, "path": path, "action": action, "left": times})

    def calls(self, method: str, path_prefix: str) -> list[httpx.Request]:
        return [
            r for r in self.requests
            if r.method == method and r.url.path.startswith(path_prefix)
        ]

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for fault in self._faults:
            if fault["left"] and fault["method"] == request.method and request.url.path.startswith(fault["path"]):
                fault["left"] -= 1
                action = fault["action"]
                if action == "timeout":
                    raise httpx.ReadTimeout("simulated timeout", request=request)
                if action == "connect_error":
                    raise httpx.ConnectError("simulated connection refused", request=request)
                if isinstance(action, int):
                    return httpx.Response(action, json={"code": "SIMULATED"}, request=request)
                return httpx.Response(200, content=action.encode(), request=request)
        response = self.inner.handle_request(request)
        response.read()
        return httpx.Response(
            response.status_code, headers=response.headers, content=response.content, request=request
        )


class System:
    """Os três serviços conectados, com acesso ao estado interno para asserções."""

    def __init__(self, products: dict | None = None):
        self.inventory_app = create_inventory_app(products)
        self.payment_app = create_payment_app()
        self.inventory_spy = SpyTransport(TestClient(self.inventory_app)._transport)
        self.payment_spy = SpyTransport(TestClient(self.payment_app)._transport)
        self.order_app = create_order_app(
            inventory=httpx.Client(transport=self.inventory_spy, base_url="http://inventory"),
            payment=httpx.Client(transport=self.payment_spy, base_url="http://payment"),
        )
        self.client = TestClient(self.order_app)

    def stock(self, sku: str) -> int:
        return self.inventory_app.state.products[sku]["stock"]

    @property
    def charges(self) -> list[dict]:
        return list(self.payment_app.state.charges.values())

    def reservation_statuses(self) -> list[str]:
        return [r["status"] for r in self.inventory_app.state.reservations.values()]


@pytest.fixture
def system() -> System:
    return System()


@pytest.fixture
def order_payload():
    def build(items=None, card_token="tok_ok", customer_id="cli_123"):
        return {
            "customer_id": customer_id,
            "items": items if items is not None else [{"sku": "SKU-CAMISETA", "qty": 2}],
            "card_token": card_token,
        }
    return build


def body_of(request: httpx.Request) -> dict:
    return json.loads(request.content)

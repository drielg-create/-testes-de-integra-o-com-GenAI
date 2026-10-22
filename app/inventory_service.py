"""Serviço de Estoque (provider).

Expõe produtos e reservas de estoque. Estado em memória para facilitar os testes.
"""
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class ReservationItem(BaseModel):
    sku: str
    qty: int = Field(ge=1)


class ReservationRequest(BaseModel):
    items: list[ReservationItem] = Field(min_length=1)


DEFAULT_PRODUCTS = {
    "SKU-CAMISETA": {"name": "Camiseta", "price_cents": 4990, "stock": 10},
    "SKU-CANECA": {"name": "Caneca", "price_cents": 2950, "stock": 3},
    "SKU-ULTIMA": {"name": "Peça única", "price_cents": 15000, "stock": 1},
}


def create_inventory_app(products: dict | None = None) -> FastAPI:
    app = FastAPI(title="inventory-service")
    app.state.products = {
        sku: dict(data) for sku, data in (products or DEFAULT_PRODUCTS).items()
    }
    app.state.reservations = {}

    @app.get("/products/{sku}")
    def get_product(sku: str):
        product = app.state.products.get(sku)
        if product is None:
            raise HTTPException(404, detail={"code": "PRODUCT_NOT_FOUND", "sku": sku})
        return {"sku": sku, **product}

    @app.post("/reservations", status_code=201)
    def create_reservation(req: ReservationRequest):
        for item in req.items:
            product = app.state.products.get(item.sku)
            if product is None:
                raise HTTPException(404, detail={"code": "PRODUCT_NOT_FOUND", "sku": item.sku})
            if product["stock"] < item.qty:
                raise HTTPException(
                    409,
                    detail={"code": "OUT_OF_STOCK", "sku": item.sku, "available": product["stock"]},
                )
        for item in req.items:
            app.state.products[item.sku]["stock"] -= item.qty
        reservation_id = f"res_{uuid.uuid4().hex[:12]}"
        app.state.reservations[reservation_id] = {
            "id": reservation_id,
            "status": "held",
            "items": [i.model_dump() for i in req.items],
        }
        return app.state.reservations[reservation_id]

    @app.post("/reservations/{reservation_id}/confirm")
    def confirm_reservation(reservation_id: str):
        reservation = _get_held(reservation_id)
        reservation["status"] = "confirmed"
        return reservation

    @app.delete("/reservations/{reservation_id}")
    def release_reservation(reservation_id: str):
        reservation = _get_held(reservation_id)
        for item in reservation["items"]:
            app.state.products[item["sku"]]["stock"] += item["qty"]
        reservation["status"] = "released"
        return reservation

    def _get_held(reservation_id: str) -> dict:
        reservation = app.state.reservations.get(reservation_id)
        if reservation is None:
            raise HTTPException(404, detail={"code": "RESERVATION_NOT_FOUND"})
        if reservation["status"] != "held":
            raise HTTPException(409, detail={"code": "RESERVATION_NOT_HELD"})
        return reservation

    return app

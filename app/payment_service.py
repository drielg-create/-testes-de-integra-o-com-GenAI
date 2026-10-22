"""Serviço de Pagamentos (provider).

Cobra cartões tokenizados. Exige o header Idempotency-Key: repetir a mesma chave
devolve a cobrança original em vez de cobrar duas vezes.
"""
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

DECLINED_TOKEN = "tok_declined"


class ChargeRequest(BaseModel):
    amount_cents: int = Field(gt=0)
    card_token: str = Field(min_length=1)
    order_id: str


def create_payment_app() -> FastAPI:
    app = FastAPI(title="payment-service")
    app.state.charges = {}  # idempotency_key -> charge

    @app.post("/charges", status_code=201)
    def create_charge(
        req: ChargeRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        if not idempotency_key:
            raise HTTPException(400, detail={"code": "IDEMPOTENCY_KEY_REQUIRED"})
        if idempotency_key in app.state.charges:
            return JSONResponse(app.state.charges[idempotency_key], status_code=200)
        if req.card_token == DECLINED_TOKEN:
            raise HTTPException(402, detail={"code": "CARD_DECLINED"})
        charge = {
            "charge_id": f"ch_{uuid.uuid4().hex[:12]}",
            "status": "approved",
            "amount_cents": req.amount_cents,
            "order_id": req.order_id,
        }
        app.state.charges[idempotency_key] = charge
        return charge

    return app

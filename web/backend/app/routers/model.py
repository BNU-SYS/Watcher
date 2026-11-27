"""Model configuration connectivity check."""

from __future__ import annotations

from fastapi import APIRouter

from ..model_service import verify_model
from ..schemas import ModelVerifyOut, ModelVerifyRequest

router = APIRouter(prefix="/model", tags=["model"])


@router.post("/verify", response_model=ModelVerifyOut)
async def verify(payload: ModelVerifyRequest) -> ModelVerifyOut:
    result = await verify_model(payload.base_url, payload.model, payload.api_key)
    return ModelVerifyOut(**result)

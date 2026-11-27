"""Detection capability catalog."""

from __future__ import annotations

from fastapi import APIRouter

from ..catalog import get_catalog
from ..schemas import CatalogOut

router = APIRouter(tags=["catalog"])


@router.get("/catalog", response_model=CatalogOut)
def read_catalog() -> CatalogOut:
    return CatalogOut.model_validate(get_catalog())

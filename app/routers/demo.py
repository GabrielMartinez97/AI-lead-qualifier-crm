from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.seed_service import seed_initial_crm_data, trigger_demo_scenario

router = APIRouter(prefix="/demo", tags=["Recruiter Live Simulator & Seed"])


@router.post("/seed")
def seed_crm_endpoint(
    force_reset: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restaura o inicializa la base de datos con 6 leads B2B realistas en distintas etapas del pipeline."""
    return seed_initial_crm_data(db=db, force_reset=force_reset)


@router.post("/scenario/{scenario_key}", status_code=status.HTTP_201_CREATED)
def run_scenario_endpoint(
    scenario_key: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Dispara en 1 clic un escenario de prueba (enterprise_hot, typeform_webhook, meta_ads_webhook, cold_nurture, disqualified_student)."""
    try:
        return trigger_demo_scenario(db=db, scenario_key=scenario_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

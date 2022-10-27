from fastapi import APIRouter
import continuous_deployment.routes.update

router = APIRouter()
router.include_router(continuous_deployment.routes.update.router)

from fastapi import APIRouter
import campaigns.extended_classes_pack.routes.consider

router = APIRouter()
router.include_router(campaigns.extended_classes_pack.routes.consider.router)

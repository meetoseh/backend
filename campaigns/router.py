from fastapi import APIRouter
import campaigns.extended_classes_pack.router

router = APIRouter()
router.include_router(
    campaigns.extended_classes_pack.router.router, prefix="/extended_classes_pack"
)

from fastapi import APIRouter
import campaigns.extended_classes_pack.router
import campaigns.login_test.router

router = APIRouter()
router.include_router(
    campaigns.extended_classes_pack.router.router, prefix="/extended_classes_pack"
)
router.include_router(campaigns.login_test.router.router, prefix="/login_test")

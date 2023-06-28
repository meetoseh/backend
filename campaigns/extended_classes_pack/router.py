from fastapi import APIRouter
import campaigns.extended_classes_pack.routes.consider
import campaigns.extended_classes_pack.routes.create_purchase_link
import campaigns.extended_classes_pack.routes.started

router = APIRouter()
router.include_router(campaigns.extended_classes_pack.routes.consider.router)
router.include_router(
    campaigns.extended_classes_pack.routes.create_purchase_link.router
)
router.include_router(campaigns.extended_classes_pack.routes.started.router)

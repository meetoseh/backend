from fastapi import APIRouter
import notifications.routes.complete
import notifications.inapp.router


router = APIRouter()
router.include_router(notifications.routes.complete.router)
router.include_router(notifications.inapp.router.router, prefix="/inapp")

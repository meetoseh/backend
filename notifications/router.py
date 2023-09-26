from fastapi import APIRouter
import notifications.inapp.router
import notifications.push.router


router = APIRouter()
router.include_router(notifications.inapp.router.router, prefix="/inapp")
router.include_router(notifications.push.router.router, prefix="/push")

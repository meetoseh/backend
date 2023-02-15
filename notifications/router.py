from fastapi import APIRouter
import notifications.routes.complete

router = APIRouter()
router.include_router(notifications.routes.complete.router)

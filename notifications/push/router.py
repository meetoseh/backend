from fastapi import APIRouter
import notifications.push.routes.create_push_token


router = APIRouter()
router.include_router(notifications.push.routes.create_push_token.router)

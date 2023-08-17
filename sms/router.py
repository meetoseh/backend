from fastapi import APIRouter
import sms.routes.webhook

router = APIRouter()
router.include_router(sms.routes.webhook.router)

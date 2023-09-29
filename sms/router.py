from fastapi import APIRouter
import sms.routes.inbound_message_webhook
import sms.routes.webhook

router = APIRouter()
router.include_router(sms.routes.inbound_message_webhook.router)
router.include_router(sms.routes.webhook.router)

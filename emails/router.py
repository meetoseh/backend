from fastapi import APIRouter
import emails.routes.sns_mail_webhook
import emails.routes.authorize_templating

router = APIRouter()
router.include_router(emails.routes.sns_mail_webhook.router)
router.include_router(emails.routes.authorize_templating.router)

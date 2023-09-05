from fastapi import APIRouter
import emails.routes.sns_mail_webhook

router = APIRouter()
router.include_router(emails.routes.sns_mail_webhook.router)

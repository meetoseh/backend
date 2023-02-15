from fastapi import APIRouter
import phones.routes.finish_verify
import phones.routes.start_verify
import phones.routes.twilio_callback


router = APIRouter()
router.include_router(phones.routes.finish_verify.router)
router.include_router(phones.routes.start_verify.router)
router.include_router(phones.routes.twilio_callback.router)

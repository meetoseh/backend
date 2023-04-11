from fastapi import APIRouter
import vip_chat_requests.actions.routes.create
import vip_chat_requests.actions.routes.read

router = APIRouter()
router.include_router(vip_chat_requests.actions.routes.create.router)
router.include_router(vip_chat_requests.actions.routes.read.router)

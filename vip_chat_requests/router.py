from fastapi import APIRouter
import vip_chat_requests.routes.create
import vip_chat_requests.routes.mine
import vip_chat_requests.routes.read
import vip_chat_requests.actions.router


router = APIRouter()
router.include_router(vip_chat_requests.routes.create.router)
router.include_router(vip_chat_requests.routes.mine.router)
router.include_router(vip_chat_requests.routes.read.router)
router.include_router(vip_chat_requests.actions.router.router, prefix="/actions")

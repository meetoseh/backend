from fastapi import APIRouter
import oauth.routes.apple_callback
import oauth.routes.callback
import oauth.routes.prepare
import oauth.routes.refresh

router = APIRouter()
router.include_router(oauth.routes.apple_callback.router)
router.include_router(oauth.routes.callback.router)
router.include_router(oauth.routes.prepare.router)
router.include_router(oauth.routes.refresh.router)

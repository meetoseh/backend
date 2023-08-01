from fastapi import APIRouter
import oauth.routes.apple_callback
import oauth.routes.callback
import oauth.routes.code
import oauth.routes.prepare
import oauth.routes.refresh
import oauth.routes.token

router = APIRouter()
router.include_router(oauth.routes.apple_callback.router)
router.include_router(oauth.routes.callback.router)
router.include_router(oauth.routes.code.router)
router.include_router(oauth.routes.prepare.router)
router.include_router(oauth.routes.refresh.router)
router.include_router(oauth.routes.token.router)

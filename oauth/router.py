from fastapi import APIRouter
import oauth.routes.apple_callback
import oauth.routes.callback
import oauth.routes.merge_confirm
import oauth.routes.merge_start
import oauth.routes.prepare_for_merge
import oauth.routes.prepare
import oauth.routes.refresh
import oauth.routes.token
import oauth.siwo.router
import oauth.passkeys.router
import oauth.silent.router


router = APIRouter()
router.include_router(oauth.routes.apple_callback.router)
router.include_router(oauth.routes.callback.router)
router.include_router(oauth.routes.merge_confirm.router)
router.include_router(oauth.routes.merge_start.router)
router.include_router(oauth.routes.prepare_for_merge.router)
router.include_router(oauth.routes.prepare.router)
router.include_router(oauth.routes.refresh.router)
router.include_router(oauth.routes.token.router)
router.include_router(oauth.siwo.router.router, prefix="/siwo")
router.include_router(oauth.passkeys.router.router, prefix="/passkeys")
router.include_router(oauth.silent.router.router, prefix="/silent")

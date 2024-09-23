from fastapi import APIRouter
import oauth.passkeys.routes.authenticate_begin
import oauth.passkeys.routes.authenticate_login_complete
import oauth.passkeys.routes.authenticate_merge_complete
import oauth.passkeys.routes.register_begin
import oauth.passkeys.routes.register_login_complete
import oauth.passkeys.routes.register_merge_complete

router = APIRouter()
router.include_router(oauth.passkeys.routes.authenticate_begin.router)
router.include_router(oauth.passkeys.routes.authenticate_login_complete.router)
router.include_router(oauth.passkeys.routes.authenticate_merge_complete.router)
router.include_router(oauth.passkeys.routes.register_begin.router)
router.include_router(oauth.passkeys.routes.register_login_complete.router)
router.include_router(oauth.passkeys.routes.register_merge_complete.router)

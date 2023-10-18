from fastapi import APIRouter
import oauth.siwo.routes.acknowledge
import oauth.siwo.routes.check
import oauth.siwo.routes.complete_verification
import oauth.siwo.routes.create_identity
import oauth.siwo.routes.exchange_for_code
import oauth.siwo.routes.login
import oauth.siwo.routes.request_verification
import oauth.siwo.routes.reset_password
import oauth.siwo.routes.update_password

router = APIRouter()
router.include_router(oauth.siwo.routes.acknowledge.router)
router.include_router(oauth.siwo.routes.check.router)
router.include_router(oauth.siwo.routes.complete_verification.router)
router.include_router(oauth.siwo.routes.create_identity.router)
router.include_router(oauth.siwo.routes.exchange_for_code.router)
router.include_router(oauth.siwo.routes.login.router)
router.include_router(oauth.siwo.routes.request_verification.router)
router.include_router(oauth.siwo.routes.reset_password.router)
router.include_router(oauth.siwo.routes.update_password.router)

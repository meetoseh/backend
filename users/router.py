from fastapi import APIRouter
import users.routes.read
import users.routes.read_attribution
import users.me.router
import users.tokens.router

router = APIRouter()
router.include_router(users.routes.read.router)
router.include_router(users.routes.read_attribution.router)

router.include_router(users.me.router.router, prefix="/me")
router.include_router(users.tokens.router.router, prefix="/tokens")

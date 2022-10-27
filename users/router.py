from fastapi import APIRouter
import users.tokens.router
import users.routes.create

router = APIRouter()
router.include_router(users.tokens.router.router, prefix="/tokens")
router.include_router(users.routes.create.router)

from fastapi import APIRouter
import users.tokens.routes.create
import users.tokens.routes.delete
import users.tokens.routes.update
import users.tokens.routes.read

router = APIRouter()
router.include_router(users.tokens.routes.create.router)
router.include_router(users.tokens.routes.delete.router)
router.include_router(users.tokens.routes.update.router)
router.include_router(users.tokens.routes.read.router)

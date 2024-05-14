from fastapi import APIRouter
import users.me.screens.routes.peek
import users.me.screens.routes.pop
import users.me.screens.routes.trace

router = APIRouter()
router.include_router(users.me.screens.routes.peek.router)
router.include_router(users.me.screens.routes.pop.router)
router.include_router(users.me.screens.routes.trace.router)

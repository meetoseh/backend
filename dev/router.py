from fastapi import APIRouter
import dev.routes.login
import dev.routes.merge


router = APIRouter()
router.include_router(dev.routes.login.router)
router.include_router(dev.routes.merge.router)

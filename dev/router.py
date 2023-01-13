from fastapi import APIRouter
import dev.routes.login


router = APIRouter()
router.include_router(dev.routes.login.router)

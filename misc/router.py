from fastapi import APIRouter
import misc.routes.now


router = APIRouter()
router.include_router(misc.routes.now.router)

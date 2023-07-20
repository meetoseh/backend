from fastapi import APIRouter
import interests.routes.read


router = APIRouter()
router.include_router(interests.routes.read.router)

from fastapi import APIRouter
import emotions.routes.read


router = APIRouter()
router.include_router(emotions.routes.read.router)

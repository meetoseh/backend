from fastapi import APIRouter
import journeys.background_images.router


router = APIRouter()
router.include_router(
    journeys.background_images.router.router, prefix="/background_images"
)

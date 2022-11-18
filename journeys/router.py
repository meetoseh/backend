from fastapi import APIRouter
import journeys.background_images.router
import journeys.audio_contents.router
import journeys.events.router


router = APIRouter()
router.include_router(
    journeys.background_images.router.router, prefix="/background_images"
)
router.include_router(journeys.audio_contents.router.router, prefix="/audio_contents")
router.include_router(journeys.events.router.router, prefix="/events")

from fastapi import APIRouter
import journeys.background_images.router
import journeys.audio_contents.router
import journeys.events.router
import journeys.routes.dev_show
import journeys.routes.dev_start_session


router = APIRouter()
router.include_router(
    journeys.background_images.router.router, prefix="/background_images"
)
router.include_router(journeys.audio_contents.router.router, prefix="/audio_contents")
router.include_router(journeys.events.router.router, prefix="/events")
router.include_router(journeys.routes.dev_show.router)
router.include_router(journeys.routes.dev_start_session.router)

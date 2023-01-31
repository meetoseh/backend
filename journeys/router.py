from fastapi import APIRouter
import journeys.background_images.router
import journeys.audio_contents.router
import journeys.events.router
import journeys.subcategories.router
import journeys.routes.create
import journeys.routes.delete
import journeys.routes.dev_show
import journeys.routes.dev_start_session
import journeys.routes.give_feedback
import journeys.routes.patch
import journeys.routes.profile_pictures
import journeys.routes.read
import journeys.routes.undelete


router = APIRouter()
router.include_router(
    journeys.background_images.router.router, prefix="/background_images"
)
router.include_router(journeys.audio_contents.router.router, prefix="/audio_contents")
router.include_router(journeys.events.router.router, prefix="/events")
router.include_router(journeys.subcategories.router.router, prefix="/subcategories")
router.include_router(journeys.routes.profile_pictures.router)
router.include_router(journeys.routes.create.router)
router.include_router(journeys.routes.delete.router)
router.include_router(journeys.routes.patch.router)
router.include_router(journeys.routes.read.router)
router.include_router(journeys.routes.undelete.router)
router.include_router(journeys.routes.give_feedback.router)


router.include_router(journeys.routes.dev_show.router)
router.include_router(journeys.routes.dev_start_session.router)

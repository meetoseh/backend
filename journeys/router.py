from fastapi import APIRouter
import journeys.background_images.router
import journeys.emotions.router
import journeys.audio_contents.router
import journeys.subcategories.router
import journeys.introductory.router
import journeys.public_links.router
import journeys.routes.check_if_shareable
import journeys.routes.confirm_share_link_view
import journeys.routes.create_share_link
import journeys.routes.create
import journeys.routes.delete
import journeys.routes.follow_share_link
import journeys.routes.give_feedback
import journeys.routes.patch
import journeys.routes.read_canonical_url
import journeys.routes.read
import journeys.routes.start_interactive_prompt
import journeys.routes.undelete


router = APIRouter()
router.include_router(
    journeys.background_images.router.router, prefix="/background_images"
)
router.include_router(journeys.emotions.router.router, prefix="/emotions")
router.include_router(journeys.audio_contents.router.router, prefix="/audio_contents")
router.include_router(journeys.subcategories.router.router, prefix="/subcategories")
router.include_router(journeys.introductory.router.router, prefix="/introductory")
router.include_router(journeys.public_links.router.router, prefix="/public_links")
router.include_router(journeys.routes.check_if_shareable.router)
router.include_router(journeys.routes.confirm_share_link_view.router)
router.include_router(journeys.routes.create_share_link.router)
router.include_router(journeys.routes.create.router)
router.include_router(journeys.routes.delete.router)
router.include_router(journeys.routes.follow_share_link.router)
router.include_router(journeys.routes.patch.router)
router.include_router(journeys.routes.read_canonical_url.router)
router.include_router(journeys.routes.read.router)
router.include_router(journeys.routes.undelete.router)
router.include_router(journeys.routes.start_interactive_prompt.router)
router.include_router(journeys.routes.give_feedback.router)

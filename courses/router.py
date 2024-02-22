from fastapi import APIRouter
import courses.routes.activate
import courses.routes.attach_free
import courses.routes.attach
import courses.routes.start_next
import courses.routes.advance

import courses.routes.start_download
import courses.routes.start_download_with_code
import courses.routes.finish_download
import courses.routes.start_journey_download
import courses.routes.start_journey

import courses.routes.create
import courses.routes.patch
import courses.routes.read
import courses.routes.read_public

import courses.background_images.router
import courses.hero_images.router
import courses.journeys.router
import courses.logos.router
import courses.videos.router

router = APIRouter()
router.include_router(courses.routes.activate.router)
router.include_router(courses.routes.attach_free.router)
router.include_router(courses.routes.attach.router)
router.include_router(courses.routes.start_next.router)
router.include_router(courses.routes.advance.router)

router.include_router(courses.routes.start_download.router)
router.include_router(courses.routes.start_download_with_code.router)
router.include_router(courses.routes.finish_download.router)
router.include_router(courses.routes.start_journey_download.router)
router.include_router(courses.routes.start_journey.router)

router.include_router(courses.routes.create.router)
router.include_router(courses.routes.patch.router)
router.include_router(courses.routes.read.router)
router.include_router(courses.routes.read_public.router)

router.include_router(
    courses.background_images.router.router, prefix="/background_images"
)
router.include_router(courses.hero_images.router.router, prefix="/hero_images")
router.include_router(courses.journeys.router.router, prefix="/journeys")
router.include_router(courses.logos.router.router, prefix="/logos")
router.include_router(courses.videos.router.router, prefix="/videos")

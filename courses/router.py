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

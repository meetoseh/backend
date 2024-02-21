from fastapi import APIRouter
import courses.videos.routes.create
import courses.videos.routes.read

import courses.videos.thumbnails.router

router = APIRouter()
router.include_router(courses.videos.routes.create.router)
router.include_router(courses.videos.routes.read.router)

router.include_router(courses.videos.thumbnails.router.router, prefix="/thumbnails")

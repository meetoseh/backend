from fastapi import APIRouter
import courses.videos.thumbnails.routes.create
import courses.videos.thumbnails.routes.read

router = APIRouter()

router.include_router(courses.videos.thumbnails.routes.create.router)
router.include_router(courses.videos.thumbnails.routes.read.router)

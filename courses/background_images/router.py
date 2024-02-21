from fastapi import APIRouter
import courses.background_images.routes.create
import courses.background_images.routes.read

router = APIRouter()

router.include_router(courses.background_images.routes.create.router)
router.include_router(courses.background_images.routes.read.router)

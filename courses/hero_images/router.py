from fastapi import APIRouter
import courses.hero_images.routes.create
import courses.hero_images.routes.read

router = APIRouter()

router.include_router(courses.hero_images.routes.create.router)
router.include_router(courses.hero_images.routes.read.router)

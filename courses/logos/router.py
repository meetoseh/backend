from fastapi import APIRouter
import courses.logos.routes.create
import courses.logos.routes.read

router = APIRouter()

router.include_router(courses.logos.routes.create.router)
router.include_router(courses.logos.routes.read.router)

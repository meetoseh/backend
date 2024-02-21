from fastapi import APIRouter
import courses.journeys.routes.create
import courses.journeys.routes.delete
import courses.journeys.routes.patch
import courses.journeys.routes.read

router = APIRouter()
router.include_router(courses.journeys.routes.create.router)
router.include_router(courses.journeys.routes.delete.router)
router.include_router(courses.journeys.routes.patch.router)
router.include_router(courses.journeys.routes.read.router)

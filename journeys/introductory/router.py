from fastapi import APIRouter
import journeys.introductory.routes.create
import journeys.introductory.routes.delete
import journeys.introductory.routes.read

router = APIRouter()
router.include_router(journeys.introductory.routes.create.router)
router.include_router(journeys.introductory.routes.delete.router)
router.include_router(journeys.introductory.routes.read.router)

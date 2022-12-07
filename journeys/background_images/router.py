from fastapi import APIRouter
import journeys.background_images.routes.create
import journeys.background_images.routes.read


router = APIRouter()

router.include_router(journeys.background_images.routes.create.router)
router.include_router(journeys.background_images.routes.read.router)

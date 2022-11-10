from fastapi import APIRouter
import journeys.background_images.routes.create


router = APIRouter()

router.include_router(journeys.background_images.routes.create.router)

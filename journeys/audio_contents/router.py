from fastapi import APIRouter
import journeys.audio_contents.routes.create
import journeys.audio_contents.routes.read


router = APIRouter()
router.include_router(journeys.audio_contents.routes.create.router)
router.include_router(journeys.audio_contents.routes.read.router)

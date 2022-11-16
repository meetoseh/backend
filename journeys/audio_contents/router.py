from fastapi import APIRouter
import journeys.audio_contents.routes.create


router = APIRouter()
router.include_router(journeys.audio_contents.routes.create.router)

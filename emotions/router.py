from fastapi import APIRouter
import emotions.routes.read
import emotions.routes.retrieve_daily_emotions
import emotions.routes.start_related_journey

router = APIRouter()
router.include_router(emotions.routes.read.router)
router.include_router(emotions.routes.retrieve_daily_emotions.router)
router.include_router(emotions.routes.start_related_journey.router)

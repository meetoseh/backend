from fastapi import APIRouter
import journeys.emotions.routes.create
import journeys.emotions.routes.delete
import journeys.emotions.routes.info


router = APIRouter()

router.include_router(journeys.emotions.routes.create.router)
router.include_router(journeys.emotions.routes.delete.router)
router.include_router(journeys.emotions.routes.info.router)

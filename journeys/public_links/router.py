from fastapi import APIRouter
import journeys.public_links.routes.start


router = APIRouter()
router.include_router(journeys.public_links.routes.start.router)

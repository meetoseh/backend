from fastapi import APIRouter
import daily_events.routes.add_journey
import daily_events.routes.create
import daily_events.routes.delete
import daily_events.routes.premiere
import daily_events.routes.read
import daily_events.routes.remove_journey
import daily_events.routes.unpremiere

router = APIRouter()
router.include_router(daily_events.routes.create.router)
router.include_router(daily_events.routes.delete.router)
router.include_router(daily_events.routes.read.router)

router.include_router(daily_events.routes.add_journey.router)
router.include_router(daily_events.routes.remove_journey.router)

router.include_router(daily_events.routes.premiere.router)
router.include_router(daily_events.routes.unpremiere.router)

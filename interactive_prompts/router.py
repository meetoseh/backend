from fastapi import APIRouter
import routes.profile_pictures
import events.router

router = APIRouter()
router.include_router(routes.profile_pictures.router)
router.include_router(events.router.router, prefix="/events")

from fastapi import APIRouter
import onboarding.videos.thumbnails.routes.create
import onboarding.videos.thumbnails.routes.read

router = APIRouter()

router.include_router(onboarding.videos.thumbnails.routes.create.router)
router.include_router(onboarding.videos.thumbnails.routes.read.router)

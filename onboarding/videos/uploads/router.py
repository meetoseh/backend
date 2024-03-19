from fastapi import APIRouter
import onboarding.videos.uploads.routes.create
import onboarding.videos.uploads.routes.read

router = APIRouter()
router.include_router(onboarding.videos.uploads.routes.create.router)
router.include_router(onboarding.videos.uploads.routes.read.router)

from fastapi import APIRouter
import onboarding.videos.thumbnails.router
import onboarding.videos.uploads.router

import onboarding.videos.routes.create
import onboarding.videos.routes.patch
import onboarding.videos.routes.read

router = APIRouter()
router.include_router(onboarding.videos.thumbnails.router.router, prefix="/thumbnails")
router.include_router(onboarding.videos.uploads.router.router, prefix="/uploads")

router.include_router(onboarding.videos.routes.create.router)
router.include_router(onboarding.videos.routes.patch.router)
router.include_router(onboarding.videos.routes.read.router)

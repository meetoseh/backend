from fastapi import APIRouter

import onboarding.routes.read_welcome_video
import onboarding.routes.track_possible_new_install

import onboarding.videos.router


router = APIRouter()
router.include_router(onboarding.routes.read_welcome_video.router)
router.include_router(onboarding.routes.track_possible_new_install.router)
router.include_router(onboarding.videos.router.router, prefix="/videos")

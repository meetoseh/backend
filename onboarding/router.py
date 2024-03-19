from fastapi import APIRouter

import onboarding.videos.router

router = APIRouter()
router.include_router(onboarding.videos.router.router, prefix="/videos")

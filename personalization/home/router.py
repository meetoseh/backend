from fastapi import APIRouter
import personalization.home.images.router

router = APIRouter()
router.include_router(personalization.home.images.router.router, prefix="/images")

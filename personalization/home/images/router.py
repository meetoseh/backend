from fastapi import APIRouter
import personalization.home.images.routes.create
import personalization.home.images.routes.patch
import personalization.home.images.routes.read

router = APIRouter()
router.include_router(personalization.home.images.routes.create.router)
router.include_router(personalization.home.images.routes.patch.router)
router.include_router(personalization.home.images.routes.read.router)

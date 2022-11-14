from fastapi import APIRouter
import image_files.routes.dev_show
import image_files.routes.image
import image_files.routes.playlist

router = APIRouter()
router.include_router(image_files.routes.dev_show.router)
router.include_router(image_files.routes.image.router)
router.include_router(image_files.routes.playlist.router)

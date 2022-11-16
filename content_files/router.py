from fastapi import APIRouter
import content_files.exports.router
import content_files.routes.dev_show
import content_files.routes.show_web_playlist
import content_files.routes.show_mobile_playlist


router = APIRouter()
router.include_router(content_files.exports.router.router, prefix="/exports")
router.include_router(content_files.routes.dev_show.router)
router.include_router(content_files.routes.show_web_playlist.router)
router.include_router(content_files.routes.show_mobile_playlist.router)

from fastapi import APIRouter
import content_files.exports.parts.router
import content_files.exports.routes.show_m3u_vod

router = APIRouter()
router.include_router(content_files.exports.parts.router.router, prefix="/parts")
router.include_router(content_files.exports.routes.show_m3u_vod.router)

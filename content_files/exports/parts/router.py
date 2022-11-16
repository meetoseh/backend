from fastapi import APIRouter
import content_files.exports.parts.routes.show

router = APIRouter()
router.include_router(content_files.exports.parts.routes.show.router)

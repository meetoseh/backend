from fastapi import APIRouter
import content_files.exports.parts.router

router = APIRouter()
router.include_router(content_files.exports.parts.router.router, prefix="/parts")

from fastapi import APIRouter
import file_uploads.routes.part


router = APIRouter()

router.include_router(file_uploads.routes.part.router)

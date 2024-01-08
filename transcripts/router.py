from fastapi import APIRouter
import transcripts.routes.show

router = APIRouter()
router.include_router(transcripts.routes.show.router)

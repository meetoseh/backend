from fastapi import APIRouter
import general_feedback.routes.create

router = APIRouter()
router.include_router(general_feedback.routes.create.router)

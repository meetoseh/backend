from fastapi import APIRouter
import client_screens.routes.read

router = APIRouter()
router.include_router(client_screens.routes.read.router)

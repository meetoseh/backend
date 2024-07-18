from fastapi import APIRouter
import journals.client_keys.routes.create

router = APIRouter()
router.include_router(journals.client_keys.routes.create.router)

from fastapi import APIRouter
import journals.client_keys.routes.create
import journals.client_keys.routes.test

router = APIRouter()
router.include_router(journals.client_keys.routes.create.router)
router.include_router(journals.client_keys.routes.test.router)

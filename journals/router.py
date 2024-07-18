from fastapi import APIRouter
import journals.client_keys.router
import journals.entries.router

router = APIRouter()
router.include_router(journals.client_keys.router.router, prefix="/client_keys")
router.include_router(journals.entries.router.router, prefix="/entries")

from fastapi import APIRouter
import admin.siwo.routes.authorize_stats
import admin.siwo.routes.exchange_stats
import admin.siwo.routes.verify_email_stats

router = APIRouter()
router.include_router(admin.siwo.routes.authorize_stats.router)
router.include_router(admin.siwo.routes.exchange_stats.router)
router.include_router(admin.siwo.routes.verify_email_stats.router)

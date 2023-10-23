from fastapi import APIRouter
import admin.siwo.routes.authorize_stats
import admin.siwo.routes.exchange_stats
import admin.siwo.routes.read_delayed_emails_set_info
import admin.siwo.routes.read_last_delayed_emails_job
import admin.siwo.routes.verify_email_stats

router = APIRouter()
router.include_router(admin.siwo.routes.authorize_stats.router)
router.include_router(admin.siwo.routes.exchange_stats.router)
router.include_router(admin.siwo.routes.read_delayed_emails_set_info.router)
router.include_router(admin.siwo.routes.read_last_delayed_emails_job.router)
router.include_router(admin.siwo.routes.verify_email_stats.router)

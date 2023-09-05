from fastapi import APIRouter
import admin.email.routes.email_event_stats
import admin.email.routes.email_send_stats
import admin.email.routes.email_webhook_stats
import admin.email.routes.read_event_queue_info
import admin.email.routes.read_last_reconciliation_job
import admin.email.routes.read_last_send_job
import admin.email.routes.read_last_stale_receipt_detection_job
import admin.email.routes.read_send_queue_info

router = APIRouter()
router.include_router(admin.email.routes.email_event_stats.router)
router.include_router(admin.email.routes.email_send_stats.router)
router.include_router(admin.email.routes.email_webhook_stats.router)
router.include_router(admin.email.routes.read_event_queue_info.router)
router.include_router(admin.email.routes.read_last_reconciliation_job.router)
router.include_router(admin.email.routes.read_last_send_job.router)
router.include_router(admin.email.routes.read_last_stale_receipt_detection_job.router)
router.include_router(admin.email.routes.read_send_queue_info.router)

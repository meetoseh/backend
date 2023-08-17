from fastapi import APIRouter
import admin.sms.routes.read_daily_sms_events
import admin.sms.routes.read_daily_sms_polling
import admin.sms.routes.read_daily_sms_sends
import admin.sms.routes.read_event_queue_info
import admin.sms.routes.read_last_receipt_reconciliation_job
import admin.sms.routes.read_last_receipt_recovery_job
import admin.sms.routes.read_last_receipt_stale_job
import admin.sms.routes.read_last_send_job
import admin.sms.routes.read_partial_sms_events
import admin.sms.routes.read_partial_sms_polling
import admin.sms.routes.read_partial_sms_send_stats
import admin.sms.routes.read_partial_sms_webhooks
import admin.sms.routes.read_pending_set_info
import admin.sms.routes.read_send_queue_info


router = APIRouter()
router.include_router(admin.sms.routes.read_daily_sms_events.router)
router.include_router(admin.sms.routes.read_daily_sms_polling.router)
router.include_router(admin.sms.routes.read_daily_sms_sends.router)
router.include_router(admin.sms.routes.read_event_queue_info.router)
router.include_router(admin.sms.routes.read_last_receipt_reconciliation_job.router)
router.include_router(admin.sms.routes.read_last_receipt_recovery_job.router)
router.include_router(admin.sms.routes.read_last_receipt_stale_job.router)
router.include_router(admin.sms.routes.read_last_send_job.router)
router.include_router(admin.sms.routes.read_partial_sms_events.router)
router.include_router(admin.sms.routes.read_partial_sms_polling.router)
router.include_router(admin.sms.routes.read_partial_sms_send_stats.router)
router.include_router(admin.sms.routes.read_partial_sms_webhooks.router)
router.include_router(admin.sms.routes.read_pending_set_info.router)
router.include_router(admin.sms.routes.read_send_queue_info.router)

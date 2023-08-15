from fastapi import APIRouter
import admin.sms.routes.read_daily_sms_sends
import admin.sms.routes.read_last_send_job
import admin.sms.routes.read_partial_sms_send_stats
import admin.sms.routes.read_pending_set_info
import admin.sms.routes.read_send_queue_info


router = APIRouter()
router.include_router(admin.sms.routes.read_daily_sms_sends.router)
router.include_router(admin.sms.routes.read_last_send_job.router)
router.include_router(admin.sms.routes.read_partial_sms_send_stats.router)
router.include_router(admin.sms.routes.read_pending_set_info.router)
router.include_router(admin.sms.routes.read_send_queue_info.router)

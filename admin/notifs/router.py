from fastapi import APIRouter
import admin.notifs.routes.read_daily_push_receipts
import admin.notifs.routes.read_daily_push_tickets
import admin.notifs.routes.read_daily_push_tokens
import admin.notifs.routes.read_last_check_job
import admin.notifs.routes.read_last_cold_to_hot_job
import admin.notifs.routes.read_last_send_job
import admin.notifs.routes.read_partial_push_receipt_stats
import admin.notifs.routes.read_partial_push_ticket_stats
import admin.notifs.routes.read_receipt_cold_set_info
import admin.notifs.routes.read_receipt_hot_set_info
import admin.notifs.routes.read_send_queue_info
import admin.notifs.routes.read_todays_push_token_stats
import admin.notifs.routes.read_total_push_tokens

router = APIRouter()
router.include_router(admin.notifs.routes.read_daily_push_receipts.router)
router.include_router(admin.notifs.routes.read_daily_push_tickets.router)
router.include_router(admin.notifs.routes.read_daily_push_tokens.router)
router.include_router(admin.notifs.routes.read_last_check_job.router)
router.include_router(admin.notifs.routes.read_last_cold_to_hot_job.router)
router.include_router(admin.notifs.routes.read_last_send_job.router)
router.include_router(admin.notifs.routes.read_partial_push_receipt_stats.router)
router.include_router(admin.notifs.routes.read_partial_push_ticket_stats.router)
router.include_router(admin.notifs.routes.read_receipt_cold_set_info.router)
router.include_router(admin.notifs.routes.read_receipt_hot_set_info.router)
router.include_router(admin.notifs.routes.read_send_queue_info.router)
router.include_router(admin.notifs.routes.read_todays_push_token_stats.router)
router.include_router(admin.notifs.routes.read_total_push_tokens.router)

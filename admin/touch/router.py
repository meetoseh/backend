from fastapi import APIRouter
import admin.touch.routes.read_buffered_link_sorted_set_info
import admin.touch.routes.read_delayed_link_clicks_sorted_set_info
import admin.touch.routes.read_last_delayed_click_persist_job
import admin.touch.routes.read_last_leaked_link_detection_job
import admin.touch.routes.read_last_log_job
import admin.touch.routes.read_last_persist_link_job
import admin.touch.routes.read_last_send_job
import admin.touch.routes.read_last_stale_detection_job
import admin.touch.routes.read_log_queue_info
import admin.touch.routes.read_pending_sorted_set_info
import admin.touch.routes.read_persistable_buffered_link_sorted_set_info
import admin.touch.routes.read_send_queue_info
import admin.touch.routes.touch_link_stats
import admin.touch.routes.touch_send_stats
import admin.touch.routes.touch_stale_stats

router = APIRouter()
router.include_router(admin.touch.routes.read_buffered_link_sorted_set_info.router)
router.include_router(
    admin.touch.routes.read_delayed_link_clicks_sorted_set_info.router
)
router.include_router(admin.touch.routes.read_last_delayed_click_persist_job.router)
router.include_router(admin.touch.routes.read_last_leaked_link_detection_job.router)
router.include_router(admin.touch.routes.read_last_log_job.router)
router.include_router(admin.touch.routes.read_last_persist_link_job.router)
router.include_router(admin.touch.routes.read_last_send_job.router)
router.include_router(admin.touch.routes.read_last_stale_detection_job.router)
router.include_router(admin.touch.routes.read_log_queue_info.router)
router.include_router(admin.touch.routes.read_pending_sorted_set_info.router)
router.include_router(
    admin.touch.routes.read_persistable_buffered_link_sorted_set_info.router
)
router.include_router(admin.touch.routes.read_send_queue_info.router)
router.include_router(admin.touch.routes.touch_link_stats.router)
router.include_router(admin.touch.routes.touch_send_stats.router)
router.include_router(admin.touch.routes.touch_stale_stats.router)

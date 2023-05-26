from fastapi import APIRouter
import notifications.inapp.routes.get_show_at
import notifications.inapp.routes.read_actions
import notifications.inapp.routes.read_sessions
import notifications.inapp.routes.start
import notifications.inapp.routes.store_action


router = APIRouter()
router.include_router(notifications.inapp.routes.get_show_at.router)
router.include_router(notifications.inapp.routes.read_actions.router)
router.include_router(notifications.inapp.routes.read_sessions.router)
router.include_router(notifications.inapp.routes.start.router)
router.include_router(notifications.inapp.routes.store_action.router)

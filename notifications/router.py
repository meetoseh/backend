from fastapi import APIRouter
import notifications.routes.complete
import notifications.routes.post_login
import notifications.routes.unsubscribe_by_email

import notifications.inapp.router
import notifications.push.router


router = APIRouter()
router.include_router(notifications.routes.complete.router)
router.include_router(notifications.routes.post_login.router)
router.include_router(notifications.routes.unsubscribe_by_email.router)

router.include_router(notifications.inapp.router.router, prefix="/inapp")
router.include_router(notifications.push.router.router, prefix="/push")

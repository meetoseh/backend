from fastapi import APIRouter

import touch_points.routes.create
import touch_points.routes.delete
import touch_points.routes.patch
import touch_points.routes.read
import touch_points.routes.send_test_email
import touch_points.routes.send_test_push
import touch_points.routes.send_test_sms

router = APIRouter()
router.include_router(touch_points.routes.create.router)
router.include_router(touch_points.routes.delete.router)
router.include_router(touch_points.routes.patch.router)
router.include_router(touch_points.routes.read.router)
router.include_router(touch_points.routes.send_test_email.router)
router.include_router(touch_points.routes.send_test_push.router)
router.include_router(touch_points.routes.send_test_sms.router)

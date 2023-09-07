from fastapi import APIRouter
import campaigns.login_test.routes.store_action


router = APIRouter()
router.include_router(campaigns.login_test.routes.store_action.router)

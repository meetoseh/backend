from fastapi import APIRouter
import users.me.routes.finish_checkout_stripe
import users.me.routes.picture
import users.me.routes.read_entitlements
import users.me.routes.read_revenue_cat_id
import users.me.routes.start_checkout_stripe
import users.me.routes.update_name

router = APIRouter()

router.include_router(users.me.routes.picture.router)
router.include_router(users.me.routes.read_entitlements.router)
router.include_router(users.me.routes.read_revenue_cat_id.router)
router.include_router(users.me.routes.start_checkout_stripe.router)
router.include_router(users.me.routes.finish_checkout_stripe.router)
router.include_router(users.me.routes.update_name.router)

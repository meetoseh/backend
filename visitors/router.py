from fastapi import APIRouter
import visitors.routes.associate_visitor_with_user
import visitors.routes.associate_visitor_with_utm
import visitors.routes.create

router = APIRouter()
router.include_router(visitors.routes.associate_visitor_with_user.router)
router.include_router(visitors.routes.associate_visitor_with_utm.router)
router.include_router(visitors.routes.create.router)

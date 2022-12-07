from fastapi import APIRouter
import journeys.subcategories.routes.create
import journeys.subcategories.routes.delete
import journeys.subcategories.routes.read
import journeys.subcategories.routes.update

router = APIRouter()
router.include_router(journeys.subcategories.routes.create.router)
router.include_router(journeys.subcategories.routes.delete.router)
router.include_router(journeys.subcategories.routes.read.router)
router.include_router(journeys.subcategories.routes.update.router)

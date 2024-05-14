from fastapi import APIRouter
import admin.client_flows.routes.flow_stats
import admin.client_flows.routes.screen_stats

import admin.client_flows.image.router
import admin.client_flows.content.router

router = APIRouter()
router.include_router(admin.client_flows.routes.flow_stats.router)
router.include_router(admin.client_flows.routes.screen_stats.router)

router.include_router(admin.client_flows.image.router.router, prefix="/image")
router.include_router(admin.client_flows.content.router.router, prefix="/content")

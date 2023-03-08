from fastapi import APIRouter
import interactive_prompts.events.routes.stats


router = APIRouter()
router.include_router(interactive_prompts.events.routes.stats.router)

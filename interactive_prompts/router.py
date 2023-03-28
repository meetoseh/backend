from fastapi import APIRouter
import interactive_prompts.routes.profile_pictures
import interactive_prompts.routes.start_public
import interactive_prompts.events.router

router = APIRouter()
router.include_router(interactive_prompts.routes.profile_pictures.router)
router.include_router(interactive_prompts.routes.start_public.router)
router.include_router(interactive_prompts.events.router.router, prefix="/events")

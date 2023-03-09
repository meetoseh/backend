from fastapi import APIRouter
import interactive_prompts.events.routes.color_prompt_response
import interactive_prompts.events.routes.join
import interactive_prompts.events.routes.leave
import interactive_prompts.events.routes.like
import interactive_prompts.events.routes.numeric_prompt_response
import interactive_prompts.events.routes.press_prompt_end_response
import interactive_prompts.events.routes.press_prompt_start_response
import interactive_prompts.events.routes.read
import interactive_prompts.events.routes.stats
import interactive_prompts.events.routes.word_prompt_response


router = APIRouter()
router.include_router(interactive_prompts.events.routes.color_prompt_response.router)
router.include_router(interactive_prompts.events.routes.join.router)
router.include_router(interactive_prompts.events.routes.leave.router)
router.include_router(interactive_prompts.events.routes.like.router)
router.include_router(interactive_prompts.events.routes.numeric_prompt_response.router)
router.include_router(
    interactive_prompts.events.routes.press_prompt_end_response.router
)
router.include_router(
    interactive_prompts.events.routes.press_prompt_start_response.router
)
router.include_router(interactive_prompts.events.routes.read.router)
router.include_router(interactive_prompts.events.routes.stats.router)
router.include_router(interactive_prompts.events.routes.word_prompt_response.router)

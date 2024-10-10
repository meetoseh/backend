from fastapi import APIRouter
import voice_notes.routes.create
import voice_notes.routes.show_audio
import voice_notes.routes.show_transcript

router = APIRouter()
router.include_router(voice_notes.routes.create.router)
router.include_router(voice_notes.routes.show_audio.router)
router.include_router(voice_notes.routes.show_transcript.router)

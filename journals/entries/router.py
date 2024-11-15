from fastapi import APIRouter
import journals.entries.routes.create_journal_entry_user_chat
import journals.entries.routes.create_journal_entry_user_voice_note
import journals.entries.routes.create_journal_entry
import journals.entries.routes.create_reflection_response
import journals.entries.routes.edit_reflection_question
import journals.entries.routes.edit_reflection_response
import journals.entries.routes.edit_summary
import journals.entries.routes.ensure_reflection_question
import journals.entries.routes.ensure_summary
import journals.entries.routes.read
import journals.entries.routes.regenerate_reflection_question
import journals.entries.routes.regenerate_summary
import journals.entries.routes.retry_system_response
import journals.entries.routes.show_journal_entry_metadata
import journals.entries.routes.sync_journal_entry

router = APIRouter()
router.include_router(journals.entries.routes.create_journal_entry_user_chat.router)
router.include_router(
    journals.entries.routes.create_journal_entry_user_voice_note.router
)
router.include_router(journals.entries.routes.create_journal_entry.router)
router.include_router(journals.entries.routes.create_reflection_response.router)
router.include_router(journals.entries.routes.edit_reflection_question.router)
router.include_router(journals.entries.routes.edit_reflection_response.router)
router.include_router(journals.entries.routes.edit_summary.router)
router.include_router(journals.entries.routes.ensure_reflection_question.router)
router.include_router(journals.entries.routes.ensure_summary.router)
router.include_router(journals.entries.routes.read.router)
router.include_router(journals.entries.routes.regenerate_reflection_question.router)
router.include_router(journals.entries.routes.regenerate_summary.router)
router.include_router(journals.entries.routes.retry_system_response.router)
router.include_router(journals.entries.routes.show_journal_entry_metadata.router)
router.include_router(journals.entries.routes.sync_journal_entry.router)

from fastapi import APIRouter
import journals.entries.routes.create_journal_entry
import journals.entries.routes.create_journal_entry_user_chat
import journals.entries.routes.retry_system_response

router = APIRouter()
router.include_router(journals.entries.routes.create_journal_entry.router)
router.include_router(journals.entries.routes.create_journal_entry_user_chat.router)
router.include_router(journals.entries.routes.retry_system_response.router)

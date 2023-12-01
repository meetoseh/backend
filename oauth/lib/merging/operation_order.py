from enum import IntEnum, auto


class OperationOrder(IntEnum):
    """Maps the step name to the operation_order value used in the corresponding log entry"""

    duplicate_identity = auto()
    create_identity = auto()
    transfer_identity = auto()
    confirm = auto()
    move_emotion_users = auto()
    move_inapp_notification_users = auto()
    move_instructor_profile_pictures = auto()
    move_interactive_prompt_sessions = auto()
    move_introductory_journeys = auto()
    move_journey_audio_contents = auto()
    move_journey_background_images = auto()
    move_journey_feedback = auto()
    move_journey_public_link_views = auto()
    move_open_stripe_checkout_sessions = auto()
    move_phone_verifications = auto()
    move_stripe_customers = auto()
    move_user_email_addresses__disable_without_hint = auto()
    move_user_email_addresses__transfer = auto()
    move_user_email_addresses__verify = auto()
    move_user_email_addresses__disable = auto()
    move_user_identities = auto()
    move_user_journeys = auto()
    move_user_likes = auto()
    move_user_phone_numbers__transfer = auto()
    move_user_phone_numbers__verify = auto()
    move_user_phone_numbers__disable = auto()
    move_user_profile_pictures = auto()
    move_user_push_tokens = auto()
    move_user_revenue_cat_ids = auto()
    move_user_touch_link_clicks = auto()
    move_user_touches = auto()
    move_vip_chat_requests__user_id = auto()
    move_vip_chat_requests__added_by_user_id = auto()
    move_visitor_users = auto()
    delete_user_daily_reminders = auto()
    move_contact_method_log = auto()
    move_daily_reminder_settings_log = auto()
    move_merge_account_log = auto()
    move_user_touch_debug_log = auto()

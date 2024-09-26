# UID Prefixes

This file is meant to search as a reference to all the UID prefixes used in the
database. Almost every table will have a `uid` field, which acts as it's primary
stable identifier. It's safe to assume that if the uid changes, then it's a
logically different field. It's NOT safe to assume that if the database id
changes then it's a logically different field.

We generally use the following format when generating uids:

- `uid = f'oseh_{table_uid_prefix}_{secrets.token_urlsafe(16)}`

The prefix improves the development and debugging experience, since it can be
used to quickly notice if we have a uid to the wrong object. For example, if the
frontend is expecting a `journey` uid, but the prefix indicates it's a
`course` uid, then we know that we have a bug. On the other hand, without
the prefix this would be nearly impossible to notice.

Note that if a uid is omitted then there is generally already an externally
generated stable text identifier for that field which we are comfortable with
sharing. In these cases a uid could be generated to get the above benefits, but
we'd rather adhere to the principle there should be only one obvious way to do
something (in this case, identify a row)

## Table UID Prefixes

- `u` - [users](db/users.md)
- `ui` - [user_identities](db/user_identities.md)
- `j` - [journeys](db/journeys.md)
- `ipe` - [interactive_prompt_events](db/interactive_prompt_events.md)
- `s3f` - [s3_files](db/s3_files.md)
- `s3fu` - [s3_file_uploads](db/s3_file_uploads.md)
- `s3fup` - [s3_file_upload_parts](db/s3_file_upload_parts.md)
- `ut` - the token in [user_tokens](db/user_tokens.md)
- `ut_uid` - the uid in [user_tokens](db/user_tokens.md)
- `cf` - [content_files](db/content_files.md)
- `cfe` - [content_file_exports](db/content_file_exports.md)
- `cfep` -[content_file_export_parts](db/content_file_export_parts.md)
- `if` - [image_files](db/image_files.md)
- `ife` - [image_file_exports](db/image_file_exports.md)
- `jbi` - [journey_background_images](db/journey_background_images.md)
- `jac` - [journey_audio_contents](db/journey_audio_contents.md)
- `ips` - [interactive_prompt_sessions](db/interactive_prompt_sessions.md)
- `iurc` - [user_revenue_cat_ids](db/user_revenue_cat_ids.md)
- `u_rc` - the app user id of the revenue cat customer in
  [user_revenue_cat_ids](db/user_revenue_cat_ids.md)
- `oscs` - [open_stripe_checkout_sessions](db/open_stripe_checkout_sessions.md)
- `sc` - [stripe_customers](db/stripe_customers.md)
- `jsc` - [journey_subcategories](db/journey_subcategories.md)
- `i` - [instructors](db/instructors.md)
- `ipp` - [instructor_profile_pictures](db/instructor_profile_pictures.md)
- `jf` - [journey_feedback](db/journey_feedback.md)
- `ij` - [introductory_journeys](db/introductory_journeys.md)
- `pv` - [phone_verifications](db/phone_verifications.md)
- `unc` - [user_notification_clicks](db/user_notification_clicks.md)
- `ip` - [interactive_prompts](db/interactive_prompts.md)
- `ipoj` - [interactive_prompt_old_journeys](db/interactive_prompt_old_journeys.md)
- `utm` - [utms](db/utms.md)
- `vu` - [visitor_users](db/visitor_users.md)
- `vutm` - [visitor_utms](db/visitor_utms.md)
- `v` - [visitors](db/visitors.md)
- `vi` - [visitor_interests](db/visitor_interests.md)
- `upp` - [user_profile_pictures](db/user_profile_pictures.md)
- `pip` - [public_interactive_prompts](db/public_interactive_prompts.md)
- `vcr` - [vip_chat_requests](db/vip_chat_requests.md)
- `vcra` - [vip_chat_request_actions](db/vip_chat_request_actions.md)
- `c` - [courses](db/courses.md)
- `cj` - [course_journeys](db/course_journeys.md)
- `cu` - [course_users](db/course_users.md)
- `ce` - [course_exports](db/course_exports.md)
- `cdl` - [course_download_links](db/course_download_links.md)
- `cldc` - [course_download_link_clicks](db/course_download_link_clicks.md)
- `g_rc` - used for guest revenue cat customers, which are used to hold entitlements
  before a real oseh user account is created
- `cuc` - [course_user_classes](db/course_user_classes.md)
- `je` - [journey_emotions](db/journey_emotions.md)
- `t` - [transcripts](db/transcripts.md)
- `tp` - [transcript_phrases](db/transcript_phrases.md)
- `cft` - [audio_content_transcripts](db/audio_content_transcripts.md)
- `eu` - [emotion_users](db/emotion_users.md)
- `ian` - DEPRECATED [inapp_notifications](db/inapp_notifications.md)
- `iana` - DEPRECATED [inapp_notification_actions.md](db/inapp_notification_actions.md)
- `ianu` - DEPRECATED [inapp_notification_users.md](db/inapp_notification_users.md)
- `ianua` - DEPRECATED [inapp_notification_user_actions.md](db/inapp_notification_user_actions.md)
- `ja` - [journey_attributions](db/journey_attributions.md)
- `jpl` - [journey_public_links](db/journey_public_links.md)
- `jplv` - [journey_public_link_views](db/journey_public_link_views.md)
- `jrp` - [journey_reddit_posts](db/journey_reddit_posts.md)
- `jpp` - [journey_pinterest_pins](db/journey_pinterest_pins.md)
- `jmp` - [journey_mastodon_posts](db/journey_mastodon_posts.md)
- `uint` - [user_interests](db/user_interests.md)
- `uj` - [user_journeys](db/user_journeys.md)
- `ul` - [user_likes](db/user_likes.md)
- `da` - [direct_accounts](db/direct_accounts.md)
- `upt` - [user_push_tokens](db/user_push_tokens.md)
- `pma` - push message attempt, used for push messages within redis
- `sms` - sms, used for sms attempts within redis (e.g., `sms:to_send`)
- `em` - email, used for email attempts with redis (e.g., `email:to_send`)
- `ef` - [email_failures](db/email_failures.md)
- `se` - [suppressed_emails](db/suppressed_emails.md)
- `lts` - [login_test_stats](db/stats/login_test_stats.md)
- `tpo` - [touch_points](db/touch_points.md)
- `tpsms` - an sms message within a touch point
- `tpem` - an email within a touch point
- `tppush` - a push message within a touch point
- `udr` - [user_daily_reminders](db/user_daily_reminders.md)
- `udrs` - [user_daily_reminder_settings](db/user_daily_reminder_settings.md)
- `drsl` - [daily_reminder_settings_log](db/logs/daily_reminder_settings_log.md)
- `utps` - [user_touch_point_states](db/user_touch_point_states.md)
- `utbl` - [user_touch_debug_log](db/logs/user_touch_debug_log.md)
- `tch` - touch, used for touches within redis (e.g., `touch:to_send`)
  and for the send intent in [user_touches](db/user_touches.md)
- `tch_r` - [user_touches](db/user_touches.md)
- `utl` - [user_touch_links](db/user_touch_links.md)
- `utlc` - [user_touch_link_clicks](db/user_touch_link_clicks.md)
- `uel` - [unsubscribed_emails_log](db/logs/unsubscribed_emails_log.md)
- `rpc` - reset password code uids (not the code itself), used to allow for a
  shorter lookup key compared to the codes themselves in e.g.
  `sign_in_with_oseh:recent_reset_password_emails`
- `sel` - [siwo_email_log](db/logs/siwo_email_log.md)
- `uea` - [user_email_addresses](db/user_email_addresses.md)
- `upn` - [user_phone_numbers](db/user_phone_numbers.md)
- `spn` - [suppressed_phone_numbers](db/suppressed_phone_numbers.md)
- `cml` - [contact_method_log](db/logs/contact_method_log.md)
- `utzl` - [user_timezone_log](db/logs/user_timezone_log.md)
- `mal` - [merge_account_log](db/logs/merge_account_log.md)
- `mal_o` - the operation_uid for [merge_account_log](db/logs/merge_account_log.md)
- `sme` - [sitemap_entries](db/sitemap_entries.md)
- `jsl` - [journey_share_links](db/journey_share_links.md)
- `jslv` - [journey_share_link_views](db/journey_share_link_views.md)
- `jp` - job progress, used for the `jobs:progress:events:{uid}` uid
- `cv` - [course_videos](db/course_videos.md)
- `cvt` - [course_video_thumbnail_images](db/course_video_thumbnail_images.md)
- `cbi` - [course_background_images](db/course_background_images.md)
- `cli` - [course_logo_images](db/course_logo_images.md)
- `chi` - [course_hero_images](db/course_hero_images.md)
- `ucl` - [user_course_likes](db/user_course_likes.md)
- `hsi` - [home_screen_images](db/home_screen_images.md)
- `uhsi` - [user_home_screen_images](db/user_home_screen_images.md)
- `uhsc` - [user_home_screen_copy](db/user_home_screen_copy.md)
- `ov` - [onboarding_videos](db/onboarding_videos.md)
- `ovu` - [onboarding_video_uploads](db/onboarding_video_uploads.md)
- `ovt` - [onboarding_video_thumbnails](db/onboarding_video_thumbnails.md)
- `ug` - [user_genders](db/user_genders.md)
- `cs` - [client_screens](db/client_screens.md)
- `cfl` - [client_flows](db/client_flows.md)
- `cfi` - [client_flow_images](db/client_flow_images.md)
- `cfcf` - [client_flow_content_files](db/client_flow_content_files.md)
- `ucs` - [user_client_screens](db/user_client_screens.md)
- `ucsl` - [user_client_screens_log](db/logs/user_client_screens_log.md)
- `ucsal` - [user_client_screens_log](db/logs/user_client_screen_actions_log.md)
- `scr` - [scratch](db/scratch.md)
- `st` - [stripe_trials](db/stripe_trials.md)
- `eim` - [email_images](db/email_images.md)
- `jne` - [journal_entries](db/journal_entries.md)
- `jei` - [journal_netry_items](db/journal_entry_items.md)
- `ujmk` - [user_journal_master_keys](db/user_journal_master_keys.md)
- `ujck` - [user_journal_client_keys](db/user_journal_client_keys.md)
- `jeil` - [journal_entry_item_log](db/logs/journal_entry_item_log.md)
- `jc` - journal chats, which is an in-memory structure used to transfer parts of a journal entry
- `jemb` - [journey_embeddings](db/journey_embeddings.md)
- `jemi` - [journey_embedding_items](db/journey_embedding_items.md)
- `gf` - [general_feedback](db/general_feedback.md)
- `srg` - [sticky_random_groups](db/sticky_random_groups.md)
- `oig` - [opt_in_groups](db/opt_in_groups.md)
- `pka` - [passkey_accounts](db/passkey_accounts.md)
- `saa` - [silentauth_accounts](db/silentauth_accounts.md)
- `vn` - [voice_notes](db/voice_notes.md)

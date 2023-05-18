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
- `u_rc` - the revenue cat id in [users](db/users.md)
- `oscs` - [open_stripe_checkout_sessions](db/open_stripe_checkout_sessions.md)
- `sc` - [stripe_customers](db/stripe_customers.md)
- `jsc` - [journey_subcategories](db/journey_subcategories.md)
- `i` - [instructors](db/instructors.md)
- `ipp` - [instructor_profile_pictures](db/instructor_profile_pictures.md)
- `jf` - [journey_feedback](db/journey_feedback.md)
- `ij` - [introductory_journeys](db/introductory_journeys.md)
- `pv` - [phone_verifications](db/phone_verifications.md)
- `uns` - [user_notification_settings](db/user_notification_settings.md)
- `unc` - [user_notification_clicks](db/user_notification_clicks.md)
- `un` - [user_notifications](db/user_notifications.md)
- `ip` - [interactive_prompts](db/interactive_prompts.md)
- `ipoj` - [interactive_prompt_old_journeys](db/interactive_prompt_old_journeys.md)
- `ukp` - [user_klaviyo_profiles](db/user_klaviyo_profiles.md)
- `ukpl` - [user_klaviyo_profile_lists](db/user_klaviyo_profile_lists.md)
- `utm` - [utms](db/utms.md)
- `vu` - [visitor_users](db/visitor_users.md)
- `vutm` - [visitor_utms](db/visitor_utms.md)
- `v` - [visitors](db/visitors.md)
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
- `ian` - [inapp_notifications](db/inapp_notifications.md)
- `iana` - [inapp_notification_actions.md](db/inapp_notification_actions.md)
- `ianu` - [inapp_notification_users.md](db/inapp_notification_users.md)
- `ianua` - [inapp_notification_user_actions.md](db/inapp_notification_user_actions.md)
- `ja` - [journey_attributions](db/journey_attributions.md)
- `jpl` - [journey_public_links](db/journey_public_links.md)
- `jplv` - [journey_public_link_views](db/journey_public_link_views.md)
- `jrp` - [journey_reddit_posts](db/journey_reddit_posts.md)
- `jpp` - [journey_pinterest_pins](db/journey_pinterest_pins.md)

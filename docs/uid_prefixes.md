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
`daily_event` uid, then we know that we have a bug. On the other hand, without
the prefix this would be nearly impossible to notice.

Note that if a uid is omitted then there is generally already an externally
generated stable text identifier for that field which we are comfortable with
sharing. In these cases a uid could be generated to get the above benefits, but
we'd rather adhere to the principle there should be only one obvious way to do
something (in this case, identify a row)

## Table UID Prefixes

- `u` - [users](db/users.md)
- `ui` - [user_identities](db/user_identities.md)
- `de` - [daily_events](db/daily_events.md)
- `j` - [journeys](db/journeys.md)
- `je` - [journey_events](db/journey_events.md)
- `dej` - [daily_event_journeys](db/daily_event_journeys.md)
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
- `js` - [journey_sessions](db/journey_sessions.md)
- `u_rc` - the revenue cat id in [users](db/users.md)
- `oscs` - [open_stripe_checkout_sessions](db/open_stripe_checkout_sessions.md)
- `sc` - [stripe_customers](db/stripe_customers.md)
- `jsc` - [journey_subcategories](db/journey_subcategories.md)
- `i` - [instructors](db/instructors.md)
- `ipp` - [instructor_profile_pictures](db/instructor_profile_pictures.md)

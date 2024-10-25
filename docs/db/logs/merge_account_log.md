# merge_account_log

This informational table gets a new entry whenever we attempt to assign an
identity to an account, except when it's the first identity for that account. In
other words, this doesn't cover the standard case where a user creates an
account by going through the standard login flow but then we have never seen
that provider flow before. This does cover when the frontend specifically asks
for provider URLs where the user can login in order to merge an identity with
their existing user on the Oseh platform, so that it can be used as an alternate
way to login to that user on the Oseh platform.

This log table focuses on just the actual merge operation itself

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external row identifer
  Uses the [uid prefix](../../uid_prefixes.md) `mal`
- `user_id (integer not null references users(id) on delete cascade)`:
  the user that will be kept after the merge, if the merge is successful
- `operation_uid (text not null)`: an identifier that is stable for
  all of the log entries that were created within effectively the same operation.
  Uses the [uid prefix](../../uid_prefixes.md) `mal_o`
- `operation_order (integer not null)`: an integer that loosely corresponds with
  the query index of the query that stored this entry. Allows sorting within an
  operation uid so that you can see the entries in the same order essentially
  the same order they are described here without having to rely on the `id`
  column.
- `phase (text not null)`: one of `initial`, `confirmed`, or `merging`. See Phases
  below
- `step (text not null)`: an enum which is used to identify which step along
  the phase this log entry is for. See the Phases section
- `step_result (text not null)`: an enum whose values depend on the step.
  See the Phases section
- `reason (text not null)`: json object, see [reason](./REASON.md). This will ensure
  at least one on the entries on an operation contains the `repo`/`file` keys, but
  most of them will not to avoid excessive repetition.
- `created_at (real not null)`: when this record was created in seconds since the
  epoch

## Phases

Each step in the underlying phase will include a description of what goes in
the `context` of the `reason`, which it might refer to as just `context`. Similarly,
the `step_result` is just referred to as `result`

### initial

This phase is requested by the client immediately after it parses the merge JWT
returned by the OAuth login phase. The client provides us the merge JWT and their
authorization token. This step doesn't occur synchronously during the oauth login
step for two reasons:

1. To avoid coupling the duration of the oauth state secret with an
   authorization token; we don't want to treat having an oauth state secret
   created for a user as being authorized to perform requests on behalf of that
   user.
2. When the user is redirected back from the provider to our callback url they
   are waiting for a redirect response before they see anything. If something
   goes wrong, or the request just takes a while, we want them to wait somewhere
   where we can indicate progress or format error messages. So we provide the redirect
   response with relatively little effort (ie., quickly), and then they perform the
   heavier request with the client fully initialized

The steps in this phase are:

1. `duplicate_identity`: Indicates that the identity was already associated with the
   user in question and thus we don't have to do anything.
   - `result`: always `yes` as we don't create an entry for this step otherwise
   - `context`: always provided, dict
     - `log`: a json object with the following keys
       - `uid`: the uid of the row in `s3_files` referencing the log file
       - `bucket`: the s3 bucket where the log file will be stored
       - `key`: the s3 key within the bucket where the log file will be stored
2. `create_identity`: Indicates if all we need to do is create a new user identity
   record and then delegate to the standard login with existing identity logic,
   which will handle syncing contact methods and store in the `contact_method_log`
   with `merge_operation_uid` in the context.
   - `result`: always `yes`, as we don't create an entry for this step otherwise
   - `context`: always provided, dict
     - `log`: a json object with the following keys
       - `uid`: the uid of the row in `s3_files` referencing the log file
       - `bucket`: the s3 bucket where the log file will be stored
       - `key`: the s3 key within the bucket where the log file will be stored
3. `transfer_identity`: Indicates that the identity exists and is already associated
   with another user on the Oseh platform, so we will need to move the identities,
   contact methods, and history over. This step will also determine if the merge is
   trivial or not. A merge is trivial if it's clear how to set up their contact methods;
   we can always merge payment info because we fully support multiple revenue cat ids
   and multiple stripe customers and this complexity is not user-visible.
   - `result`: `trivial` or `requires-input`
   - `context`: always provided, dict
     - `log`: a json object with the following keys
       - `uid`: the uid of the row in `s3_files` referencing the log file
       - `bucket`: the s3 bucket where the log file will be stored
       - `key`: the s3 key within the bucket where the log file will be stored
     - `merging`: a json object with the following keys
       - `provider`: the provider for the identity used to authorize the merging user
       - `provider_sub`: the sub from the provider for the identity used to authorize the merging user
       - `user_sub`: the sub on our end of the user associated with that identity
     - `email`: dict
       - `receives_reminders`: dict
         - `original`: true if the original account receives email reminders, i.e.,
           there is a `user_daily_reminders` row with the email channel for the original
           user. false otherwise
         - `merging`: true if the merging account receives email reminders, false otherwise
       - `verified_enabled_unsuppressed`: dict
         - `original`: list of string; each corresponding to an enabled,
           verified, unsuppressed email address for the original user
         - `merging`: list of string; each corresponding to an enabled, verified
           email address, unsuppressed for the merging user
       - `conflicts`: true if email is preventing a trivial merge, ie., either the original or
         the merging is receiving reminders and the length of the union of their verified enabled
         emails is at least 2, false otherwise
     - `phone`: dict; same as `email`, but the identifiers are phone numbers

In the case of a trivial merge, the same operation uid will then have the merging phase

### confirmed

If the initial merge attempt has the `transfer_identity` step with result `requires-input`,
the client prompts the user to select one email address and one phone number from the combined
list of both accounts. Once they have done so, we will proceed with a merge so long as both
users still exist and the email/phone hint actually corresponds to an email/phone on one of
the accounts and they provided an email iff an email was requested and they provided a phone
number iff a phone was requested. This will not consider if we didn't request an email in the
previous step but it's now required to avoid duplicate email reminders (or the analagous for
sms), or that the email/phone was no longer necessary

1. `confirm`: indicates that the user selected the indicated hints and tried to complete the
   merge. Check the result to see if the original users state and the merging identities state
   are still sufficiently similar to when the initial merge was attempted that we could proceed
   - `result`: either `success` or `failure` for if we could proceed with the merge or not,
     respectively.
   - `context`
     - `log`: a json object with the following keys
       - `uid`: the uid of the row in `s3_files` referencing the log file
       - `bucket`: the s3 bucket where the log file will be stored
       - `key`: the s3 key within the bucket where the log file will be stored
     - `merging` goes to a json object with the following keys
       - `provider`: the provider for the identity used to authorize the merging user
       - `provider_sub`: the sub from the provider for the identity used to authorize the merging user
       - `expected_user_sub`: the sub on our end of the user associated with that identity when the
         initial phase occurred
       - `user_sub`: either a string or null for the user currently associated with that identity.
         if this doesn't match the expected user sub, that is sufficient to fail the merge
     - `email` goes to a json object with the following keys
       - `hint`: either a string representing the email address provided by the user as the
         one to keep enabled or null if they did not provide one
       - `hint_is_original`: true if the email is one of the emails associated with the original user
       - `hint_is_merging`: true if the email is one of the emails associated with the merging user
     - `phone`: same structure as `email` but email addresses are swapped for phone numbers

After `confirm` with the step result `success`, the same operation uid will then have the merging phase

### merging

The general idea is we swap the `user_id` of one table at a time, keeping track
of how many records were swapped, and for really important tables (e.g.,
`user_identities`) we also track wich records came from the merging identity

Unless otherwise indicated, will have the following information:

- `phase`: `merging`
- `result`: `xfer`
- `context`: `{"rows": number}`

This list exhaustively contains every table references users in ascending
alphabetical order, with logs moved to the bottom:

1. `move_emotion_users`
2. `move_inapp_notification_users`
3. `move_instructor_profile_pictures`
4. `move_interactive_prompt_sessions`
5. `move_introductory_journeys`
6. `move_journey_audio_contents`
7. `move_journey_background_images`
8. `move_journey_feedback`
9. `move_journey_public_link_views`
10. `move_user_home_screen_images`
11. `move_open_stripe_checkout_sessions`
12. `move_phone_verifications`
13. `move_stripe_customers`

    - `context`:
      - `ids`: a list of stripe customer ids (these are strings) that are being
        moved
      - `rows`: the length of ids

14. We do not attempt to transfer `user_daily_reminder_settings`; instead, immediately
    after the transaction completes we refetch their settings and user_daily_reminder
    records to ensure they are in sync. after the merge, the user is asked to
    review their settings again.

15. `move_user_email_addresses__disable_without_hint`: if we are merging two
    accounts and don't have an email hint, i.e., there is no email conflict,
    it is possible that both accounts have enabled email addresses but at least
    one of them has email reminders disabled via `user_daily_reminder_settings`
    having `day_of_week_mask = 0` or because the email isn't verified or is
    suppressed. To handle this, we will disable all the email addresses with one
    of the two accounts, preferring to disable the merging ones if neither
    was actually receiving email notifications

    - `context`
      - `original_enabled`: the enabled email addresses
        associated with the original user.
      - `merging_enabled`: the enabled email addresses associated with the
        merging user
      - `original_receives_reminders`: true if the original account receives email
        reminders, false otherwise
      - `merging_receives_reminders`: true if the merging account receives email
        reminders
      - `disabling_merging_emails`: true if we are disabling all email addresses
        associated with the merging user. This is true if both accounts have
        enabled email addresses and the original account receives reminders.
      - `disabling_original_emails`: true if both accounts have enabled email
        addresses and we are not disabling merging emails

16. `move_user_email_addresses__transfer`: the email addresses that are simply transferred over
    because they exist on the merging user but not on the original user (case
    insensitive). This does not require writing to the contact method log, since
    the old contact method log entries will be transfered and are still accurate

    - `context`
      - `transfered`: goes to a list of json objects representing the email addresses from the
        merging user that will be transferred over without changing their state
        because they do not exist on the original user
        - `email`: the email address on the original user
        - `suppressed`: true if there is a corresponding record in suppressed_emails, false otherwise
        - `verified`: see `user_email_addresses`, as a boolean
        - `receives_notifications`: see `user_email_addresses`, as a boolean
      - `rows`: the length of transferred

17. `move_user_email_addresses__verify`: the email addresses that are verified on the
    original user because they existed for both the original user and the merging user,
    but they were only verified on the merging user. the nature of this query means it
    excludes transfered emails despite being after the transfer step. after the
    transaction we will read back from this entry to get data to write to the contact
    method log for clarity

    - `context`
      - `verified`: goes to a list of email addresses (strings)
      - `rows`: the length of verified

18. `move_user_email_addresses__disable`: the email addresses that are disabled on the
    original user because a hint email was provided and they don't match it. note that
    this occurs after emails have already been transferred and hence does not distinguish
    emails on the original user vs merging user. after the transaction completes we will
    read back from this entry to get data to write to the contact method log for clarity

    - `context`
      - `disabled`: goes to a list of email addresses (strings)
      - `rows`: the length of verified

19. `move_user_identities`
    - `context`
      - `merging`: goes to a list of json objects with the following keys from
        `user_identities`
        - `uid`
        - `provider`
        - `sub`
      - `rows`: the length of merging
20. We do not transfer `user_interests`, though they might be incidentally changed from the
    new visitors.
21. `move_user_journeys`
22. `move_user_likes` we ignore duplicates
23. `move_user_phone_numbers__disable_without_hint`: see `move_user_email_addresses__disable_without_hint`; `email` -> `phone`
24. `move_user_phone_numbers__transfer`: see `move_user_email_addresses__transfer`; `email` -> `phone`
25. `move_user_phone_numbers__verify`: see `move_user_email_addresses__verify`
26. `move_user_phone_numbers__disable`: see `move_user_email_addresses__disable`
27. `move_user_profile_pictures`: the general idea is we will keep the latest on the current
    account but copy over the merging account as non-latest. However, if the oroginal account
    doesn't have a latest item, we'll set the original accounts latest profile picture as well

    - `context`
      - `rows`: the number of rows to move over
      - `setting_latest`: true if the original account doesn't have a latest profile picture
        (and thus probably has no profile pictures) but the merging account does have a latest
        profile picture, false otherwise. If true we just update the user_id column, if false
        we first set latest to 0 on all of them before updating the user_id column

28. `move_user_push_tokens`
29. `move_user_revenue_cat_ids`

    - `context`
      - `rows`: the number of rows to move over
      - `merging`: a list of strings representing revenue cat ids that are being merged

30. We do not merge `user_tokens`; if they are using api-only auth, they can regenerate them
31. `move_user_touch_link_clicks`
32. We do not merge `user_touch_point_states` as there is no straight-forward algorithm to do so
33. `move_user_touches`
34. `move_vip_chat_requests__user_id`: refers to the `user_id` column only
35. `move_vip_chat_requests__added_by_user_id`: refers to the `added_by_user_id` column only
36. `move_visitor_users`: This record will exist if there are any visitors associated with
    the merging user, regardless of if they are actually moved over. Furthermore, within SQL
    we don't change the `user_id` column; instead we delete the records and bump the version
    on the corresponding visitors, then after the transaction we go back to check this row
    and queue the associations to the redis key `visitors:user_associations` as managing e.g.
    last click utms consistently is an involved process.
    - `context`
      - `uids`: a list of strings corresponding to visitor uids associated with the merging
        user
      - `rows`: length of uids
37. `delete_user_daily_reminders`: we simply delete the user daily reminders of
    the merging user so that we can look at this log entry after and use it to
    update user daily reminder registration stats.

    NOTE: this is moved to the bottom since it must be after both the email
    addresses and phone numbers are moved, as the user daily reminders before
    the merge are used when there is no corresponding hint to decide which set
    of contact methods to disable

    - `context`:
      - `channels`: a list of channels (strings, e.g., `"sms"`) being deleted
      - `rows`: the length of channels

38. `move_contact_method_log`: all entries have their reason updated to have a new top level
    key inserted: the `_merged_{sub}` of the merging account (to avoid duplicates in the case
    of sequential merges) and the value is a json object with the following keys:
    - `original`: sub of the original user
    - `operation_uid`: the uid of the merge operation
    - `merged_at`: the canonical timestamp of when the merge occurred
39. `move_daily_reminder_settings_log`: same strategy as `contact_method_log`
40. we do not copy over `user_timezone_log` and we do not update `timezone` on users
41. `move_merge_account_log`: same strategy as `contact_method_log`
42. `move_user_touch_debug_log`: standard update
43. `move_user_client_screens_log`: standard update
44. `delete_user_client_screens`: we will reset both the merging user and the original
    users client screen queue. this is done defensively; generally a `merge` client flow
    should be triggered after which will have `replaces=True` which obviates the need
    for this step
    - `step_result`: `delete`
    - `context`:
      - `original`: the number of rows deleted from the original user
      - `merging`: the number of rows deleted from the merging user
45. `move_journal_entries`: standard update
46. `move_user_journal_master_keys`: standard update
47. `move_user_journal_client_keys`: standard update
48. `move_opt_in_group_users__transfer`: the opt-in groups that were simply transfered
    over because they existed on the merging user but not on the original user.
    - `context`
      - `transfered`: goes to a list of group uids that were transfered over
        - `uid`: the opt in group uid
      - `rows`: the length of transfered
49. `move_opt_in_group_users__delete`: the opt-in groups that were deleted from the
    merging user because they were already associated with the original user
    - `context`
      - `deleted`: goes to a list of group uids that were deleted
        - `uid`: the opt in group uid
      - `rows`: the length of deleted
50. `move_user_goals__transfer`: if the original user no goal set and the merging
    user does, transfer the goal from the merging user to the original user
    - `context`
      - `days_per_week`: the number of days per week moved over
51. `move_user_goals__delete`: if the merging user still has a goal set, delete it
    - `context`
      - `days_per_week`: the days per week on the deleted record
52. `move_voice_notes`: standard update
53. `move_name`: we set the `given_name` and `family_name` of the original user to the
    values on the merging user if they are null on the original user but not null on
    the merging user.
    - `context`:
      - `original_given_name`: the given name of the original user
      - `merging_given_name`: the given name of the merging user
      - `given_name_assignment_required`: true if `merging_given_name` is not null and
        `original_given_name` is null, false otherwise
      - `original_family_name`: the family name of the original user
      - `merging_family_name`: the family name of the merging user
      - `family_name_assignment_required`: true if `merging_family_name` is not null and
        `original_family_name` is null, false otherwise
54. `move_admin`: we set `admin` to `1` on the original user if it was 0 and it is `1`
    on the merging user
55. `move_created_at`: we set the `created_at` timestamp of the original user to the
    earlier of the original users created at and the merging users created at. this may
    mean that, incidentally, some computed attribution information is excluded.
    - `context`:
      - `original_created_at`: the created at of the original user
      - `merging_created_at`: the created at of the merging user
      - `assignment_required`: true if `merging_created_at < original_created_at`, false
        otherwise

## Schema

```sql
CREATE TABLE merge_account_log (
  id INTEGER PRIMARY KEY,
  uid TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  operation_uid TEXT NOT NULL,
  operation_order INTEGER NOT NULL,
  phase TEXT NOT NULL,
  step TEXT NOT NULL,
  step_result TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at REAL NOT NULL
);

/* Foreign key */
CREATE INDEX merge_account_log_user_id_idx ON merge_account_log(user_id);

/* Pseudo-self reference foreign key and sort */
CREATE INDEX merge_account_log_operation_uid_order_idx ON merge_account_log(operation_uid, operation_order);
```

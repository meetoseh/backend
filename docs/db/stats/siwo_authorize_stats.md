# siwo_authorize_stats

This table contains Sign in with Oseh authorize page stats, specifically,
it describes how many times an accounts existence is checked, how many
security elevations are required, how many logins are made, how many
accounts are created, and how many reset password requests are made.

Details for Sign in with Oseh are available on the Sign in with Oseh
dashboard in the admin area.

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `check_attempts (integer not null)`: how many users attempted to check if an
  account existed with an email address
- `check_failed (integer not null)`: of the checks attempted, how many were
  rejected outright because of a bad client id, redirect url, csrf token, or
  because they provided an invalid email verification code
- `check_failed_breakdown (text not null)`: goes to a json object breaking
  down `check_failed` by `{reason}:{details}`, e.g., `bad_csrf:malformed`. The
  reason is one of:
  - `bad_client` - the client id and redirect url do not match a known pair. details
    is one of `unknown` or `url` for if the client ID is unknown or doesn't have that
    redirect url, respectively
  - `bad_csrf` - the csrf token provided is invalid. the reason is one of:
    - `malformed` - couldn't be interpreted as a JWT
    - `incomplete` - the JWT is missing required claims
    - `signature` - the signature is invalid
    - `bad_iss` - the issuer does not match the expected value
    - `bad_aud` - the audience does not match the expected value
    - `expired` - the JWT is expired
    - `already_used` - the JTI has already been seen
  - `blocked` - we wanted to do a security check but the email is on the suppressed
    emails list. the reason matches the breakdown for `check_elevated`
  - `bad_code` - the code provided is invalid. the reason is one of:
    - `unknown` - the code was not in the sorted set containing recent codes we sent the user, so
      it's either just wrong or pretty old
    - `expired` - the code has been sent to the user somewhat recently, but not recently enough
    - `bogus` - we randomly generated a code independently, didn't send it to
      them, and then they later provided us that code. this is a very strong
      sign they are successfully guessing our codes!
    - `lost` - the code was in the sorted set containing recent codes we sent the user, but the
      required additional information about the code was not found in redis
    - `already_used` - the code has already been used
    - `revoked` - the code was revoked because another code has since been sent
    - `not_sent_yet` - we haven't actually sent them the code yet! this is a sign they are
      successfully guessing our codes
- `check_elevated (integer not null)`: of the checks attempted, how many did the
  backend block with a request for an email verification code
- `check_elevated_breakdown (text not null)`: goes to a json object breaking
  down `check_elevated` by

  - `visitor` means that the visitor set has a lot of email addresses in it for
    pretty new accounts. this is as strong an indictment as is possible that the client
    is maliciously creating accounts and will trigger (or extend) the global security
    check flag
  - `email` means that we have recently required a security check on that email address
    and are hence requiring it here for consistency
  - `global` means that the global security check flag was set to 1, meaning we've recently
    had the visitor check trip and are now scrutinizing everyone to make it harder for the
    visitor that caused us to do this to know if it was them who triggered the check or
    someone else
  - `ratelimit` means that the number of check account attempts in total exceeded the
    threshold and to prevent a scanning attack we need to ratelimit, but to allow
    real users we are ratelimiting indirectly using verification emails
  - `email_ratelimit` means that the number of check account attempts for that specific
    email address exceeded a threshold
  - `visitor_ratelimit` means that the number of check account attempts for that specific
    visitor exceeded a threshold. this will trigger (or extend) the global security check
    flag
  - `strange` means that the email doesn't appear to be from a standard
    provider (gmail, yahoo, etc) or otherwise appears a bit strange, e.g.,
    it contains spaces, so we're requesting an email verification code because
    we think the user made a typo
  - `disposable` means that we recognize the provider as one that provides
    disposable email addresses (we fetch the list from
    https://github.com/disposable-email-domains/disposable-email-domains).
    This is referring to emails that are created almost exclusively for
    fraud, not aliases

- `check_elevation_acknowledged (integer not null)`: of the checks elevated, how
  many were acknowledged by the client, ie., they requested the verification
  email
- `check_elevation_failed (integer not null)`: of the check elevations
  acknowledged, how many did we explicitly block due to backpressure
- `check_elevation_failed_breakdown (text not null)`: goes to a json object
  breaking down `check_elevation_failed` by
  - `bad_jwt`- the Elevation JWT provided is missing or invalid, followed by
    a colon and the specific reason, e.g., `bad_jwt:missing`:
    - `missing` - the Elevation JWT is missing
    - `malformed` - could not be interpreted as a JWT
    - `incomplete` - the JWT is missing required claims
    - `signature` - the signature is invalid
    - `bad_iss` - the issuer does not match the expected value
    - `bad_aud` - the audience does not match the expected value
    - `expired` - the JWT is expired
    - `lost` - the reason for the initial elevation could not be found when
      looking it up by JTI
    - `revoked` - the elevation JWT has been revoked
  - `backpressure:email_to_send` means we wanted to send the email immediately but there
    are too many emails on the email to send queue
  - `backpressure:delayed:total` means we wanted to send the email with a delay but there are
    too many emails on the delayed email verification queue
  - `backpressure:delayed:duration` means we wanted to send the email with a delay, but by the
    time the email reaches them it will practically be expired, and we are not doing that intentionally
- `check_elevation_succeeded (integer not null)`: of the check elevations
  acknowledged, how many did we tell the client we sent them a code for (though
  that doesn't necessarily mean we sent an email)
- `check_elevation_succeeded_breakdown (text not null)`: goes to a json object
  breaking down `check_elevation_succeeded` by `sent:{reason}`,
  `delayed:{bogus|real}:{reason}` or `unsent:{unsent_reason}:{reason}`. in all
  cases, the reason matches the original `check_elevated` reason.

  - `sent` means we queued a real verification email to be sent as soon as possible
    by pushing it to the Email To Send queue

  - `delayed` means we queued an email to be sent to the user after a bit of time
    has passed to act as a ratelimiter. the amount of time is usually
    the greater of a minimum amount of time into the future and when the next
    queued email will be sent with a small gap. The next segment is `bogus` if
    the code we included in the email wasn't the same code that we stored to
    confuse the user, and `real` means the code in the email is the same code
    we stored so it's actually possible to complete the verification.

  - `unsent` means we didn't send them a verification email. the `unsent_reason`
    will be one of

    - `suppressed`: the email address is suppressed
    - `ratelimited`: we have sent too many verification emails to that email address
      recently and don't want to spam them, even with delays
    - `deterred`: we aren't sending this email to deter human-driven fraud

- `check_succeeded (integer not null)`: of the checks attempted, how many did we
  provide a Login JWT for

- `check_succeeded_breakdown (text not null)`: a json object breaking down
  `check_succeeded` by

  - `normal`: none of our attack detection measures indicated anything was afoot
  - `code_provided`: the user provided a valid email verification code
  - `{elevation_reason}:{override_reason}`: the first value is the same as
    the reason for `check_elevated`, and `override_reason` is one of:
    - `visitor`: a visitor was provided, the email address corresponds to a
      Sign in with Oseh identity, that Sign in with Oseh identity corresponds
      to a user on the Oseh platform, and the visitor has been seen with that
      user in the last year.
    - `test_account`: the email address if for an account we explicitly gave to
      a third party (typically Google/Apple, for app review), and they don't have
      access to the underlying email address

- `login_attempted (integer not null)`: how many users attempted to exchange a
  Login JWT for a Sign in with Oseh JWT on an existing identity
- `login_failed (integer not null)`: of the logins attempted, how many were
  blocked because the account did not exist, the password was wrong, due to
  ratelimiting, or because the JWT was invalid
- `login_failed_breakdown (text not null)`: json object breaking down
  `login_failed` by `{reason}[:{details}]` where reason is one of:
  - `bad_jwt` - the login JWT provided is missing or invalid
    - `missing` - the login JWT is missing
    - `malformed` - could not be interpreted as a JWT
    - `incomplete` - the JWT is missing required claims
    - `signature` - the signature is invalid
    - `bad_iss` - the issuer does not match the expected value
    - `bad_aud` - the audience does not match the expected value
    - `expired` - the JWT is expired
    - `lost` - the additional hidden state for the JWT was not in redis
    - `revoked` - the login JWT has been revoked
  - `integrity` - there is no identity. `details` is either
    - `client` - we didn't check the database, the login JWT indicates it's for
      the create account endpoint
    - `server` - the identity existed when the login JWT was created, but it no
      longer does
  - `bad_password` - the provided password didn't match.
  - `ratelimited` - the user has provided more than 3 unique passwords with this
    login JWT, all of them were wrong, and its been less than 60 seconds since the
    last attempt. we have to ratelimit to prevent brute force attacks
- `login_succeeded (integer not null)`: of the logins attempted, how many did
  we provide a Sign in with Oseh JWT for
- `login_succeeded_breakdown (text not null)`: json object breaking down
  `login_succeeded` by
  - `no_code:unverified` they were not required to go through a verification
    request and their Sign in with Oseh identity did not have a verified email,
    so they still don't have a verified email
  - `no_code:verified` they were not required to go through a verification request
    but their Sign in with Oseh identity already had a verified email, so they
    still do
  - `code:unverified` they provided an email verification code to get the login JWT
    and logged into a Sign in with Oseh identity with an unverified email, which
    changes it to verified without them having to go through the normal process
  - `code:verified` they provided an email verification code to get the login JWT
    but their Sign in with Oseh identity already had a verified email so there was
    no change
- `create_attempted (integer not null)`: how many users attempted to exchange a
  Login JWT for a Sign in with Oseh JWT for a new identity
- `create_failed (integer not null)`: of the creates attempted, how many did we
  reject because of an integrity issue or because the JWT was invalid
- `create_failed_breakdown (text not null)`: json object breaking down
  `create_failed` by `{reason}[:{details}]` where reason is one of:
  - `bad_jwt` - same as for `login_failed`
  - `integrity` - same as for `login_failed`, but in this case it's an error if
    the identity does exist
- `create_succeeded (integer not null)`: of the creates attempted, how many did
  we create a new identity and return a Sign in with Oseh JWT for
- `create_succeeded_breakdown (text not null)`: json object breaking down
  `create_succeeded` by:
  - `code`: they provided a code to get the Login JWT, so the resulting account
    is initialized with a verified email
  - `no_code`: they did not provide a code to get the Login JWT, so the resulting
    account is initialized with an unverified email
- `password_reset_attempted (integer not null)`: how many users attempted to
  exchange a Login JWT for an email containing a password reset code being
  sent to the email of the corresponding identity
- `password_reset_failed (integer not null)`: of the password resets attempted,
  how many were blocked explicitly because the identity did not exist, the email
  is suppressed, due to ratelimiting, because the JWT was invalid, or because of
  an issue with the email templating server
- `password_reset_failed_breakdown (text not null)`: json object breaking down
  `password_reset_failed` by
  - `bad_jwt` - same as for `create_failed`
  - `integrity` - same as for `create_failed`
  - `suppressed` - we wanted to send the password reset email, but the email address
    suppressed
  - `global_ratelimited`: we have sent too many password reset emails in general which
    is a possible sign of malicious behavior
  - `uid_ratelimited`: we have sent too many password reset emails to the identity recently
    and we don't want to spam them
  - `backpressure:email_to_send`: we wanted to send an email but there were too many emails
    in the Email To Send queue
- `password_reset_confirmed (integer not null)`: of the password resets
  attempted, how many did we tell the user we sent them an email. This does not
  guarrantee we actually sent them an email
- `password_reset_confirmed_breakdown (text not null)`: goes to a json object
  which breaks down `password_reset_confirmed` by:
  - `sent` means we sent the email to be delivered as quickly as possible via the
    Email To Send queue
- `password_update_attempted (integer not null)`: how many users attempted to
  exchange a reset password code to update the password of an identity and get a
  Sign in with Oseh JWT for that identity.
- `password_update_failed (integer not null)`: of the password updates
  attempted, how many were blocked explicitly because the reset password code
  did not exist, the corresponding identity did not exist, the csrf token was
  invalid, or due to ratelimiting
- `password_update_failed_breakdown (text not null)`: goes to a json object
  which breaks down `password_update_failed` by:

  - `bad_csrf` - the csrf token is invalid; includes a sub-reason in the same
    way as `check_failed`
  - `bad_code` - the reset password code is invalid
    - `used` - the reset password code was already used
    - `dne` - the reset password code never existed or expired
  - `integrity` - the reset password code did exist, but the identity has since been
    deleted
  - `ratelimited` - there have been too many password update attempts recently. this
    is a basic global ratelimit

- `password_update_succeeded (integer not null)`: of the password updates
  attempted, how many resulted in an identity with an updated password and a
  sign in with oseh jwt for that identity being given to the client
- `password_update_succeeded_breakdown (text not null)`: goes to a json object
  which breaks down `password_update_succeeded` by

  - `was_unverified` - the identity whose password was updated did not have a verified
    email address and now does
  - `was_verified` - the identity whose password was updated already had a verified email
    address and still does

## Schema

```sql
CREATE TABLE siwo_authorize_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    check_attempts INTEGER NOT NULL,
    check_failed INTEGER NOT NULL,
    check_failed_breakdown TEXT NOT NULL,
    check_elevated INTEGER NOT NULL,
    check_elevated_breakdown TEXT NOT NULL,
    check_elevation_acknowledged INTEGER NOT NULL,
    check_elevation_failed INTEGER NOT NULL,
    check_elevation_failed_breakdown TEXT NOT NULL,
    check_elevation_succeeded INTEGER NOT NULL,
    check_elevation_succeeded_breakdown TEXT NOT NULL,
    check_succeeded INTEGER NOT NULL,
    check_succeeded_breakdown TEXT NOT NULL,
    login_attempted INTEGER NOT NULL,
    login_failed INTEGER NOT NULL,
    login_failed_breakdown TEXT NOT NULL,
    login_succeeded INTEGER NOT NULL,
    login_succeeded_breakdown TEXT NOT NULL,
    create_attempted INTEGER NOT NULL,
    create_failed INTEGER NOT NULL,
    create_failed_breakdown TEXT NOT NULL,
    create_succeeded INTEGER NOT NULL,
    create_succeeded_breakdown TEXT NOT NULL,
    password_reset_attempted INTEGER NOT NULL,
    password_reset_failed INTEGER NOT NULL,
    password_reset_failed_breakdown TEXT NOT NULL,
    password_reset_confirmed INTEGER NOT NULL,
    password_reset_confirmed_breakdown TEXT NOT NULL,
    password_update_attempted INTEGER NOT NULL,
    password_update_failed INTEGER NOT NULL,
    password_update_failed_breakdown TEXT NOT NULL,
    password_update_succeeded INTEGER NOT NULL,
    password_update_succeeded_breakdown TEXT NOT NULL
)
```

# siwo_verify_email_stats

Within Sign in with Oseh, describes how many verification emails were requested
and verifications attempted outside of the security check sometimes requested in
order to check an account (which can also result in a verified email)

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `email_requested (integer not null)`: how many verification emails were
  requested
- `email_failed (integer not null)`: how many verification emails did we
  refuse to send
- `email_failed_breakdown (text not null)`: a json object where the values
  are integer counts and the keys are `{reason}[:{details}]` (ex:
  `bad_jwt:missing` or `ratelimited`):
  - `bad_jwt` - the Sign in with Oseh JWT is missing or invalid. details are:
    - `missing` - the JWT is missing
    - `malformed` - could not be interpreted as a JWT
    - `incomplete` - the JWT is missing required claims
    - `signature` - the signature is invalid
    - `bad_iss` - the issuer does not match the expected value
    - `bad_aud` - the audience does not match the expected value
    - `expired` - the JWT is expired
    - `revoked` - the JWT has been revoked
  - `backpressure` - there are too many emails in the email to send queue
  - `ratelimited` - we have sent a verification email to the user recently
  - `integrity` - the sign in with oseh identity has been deleted
- `email_succeeded (integer not null)`: how many verification emails did we send
- `verify_attempted (integer not null)`: how many verifications by code were
  attempted
- `verify_failed (integer not null)`: how many verification codes were rejected
- `verify_failed_breakdown (text not null)`: a json object where the values
  are integer counts and the keys are `{reason}[:{details}]`

  - `bad_jwt` - the Sign in with Oseh JWT is missing or invalid. details are:
    - `missing` - the JWT is missing
    - `malformed` - could not be interpreted as a JWT
    - `incomplete` - the JWT is missing required claims
    - `signature` - the signature is invalid
    - `bad_iss` - the issuer does not match the expected value
    - `bad_aud` - the audience does not match the expected value
    - `expired` - the JWT is expired
    - `revoked` - the JWT has been revoked
  - `bad_code` - the code doesn't match one we sent them or is expired
    - `dne`: the code was not sent to them recently (or at all)
    - `expired`: the code was sent to them recently but is expired
    - `revoked`: the code was sent to them recently, but since then a newer code has been sent
    - `used`: the code was sent to them recently and was already used
  - `integrity` - the sign in with oseh identity has been deleted. we revoke
    the JWT when we see this
  - `ratelimited` - a verification code has been attempted for this email recently

- `verify_succeeded (integer not null)`: how many verification codes were accepted
- `verify_succeeded_breakdown (text not null)`: a json object where the values are
  integer counts and the keys are:
  - `was_verified` - the sign in with oseh already had a verified email and thus this
    did not result in a change
  - `was_unverified` - the sign in with oseh identity previously had an unverified
    email and now has a verified email

## Schema

```sql
CREATE TABLE siwo_verify_email_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    email_requested INTEGER NOT NULL,
    email_failed INTEGER NOT NULL,
    email_failed_breakdown TEXT NOT NULL,
    email_succeeded INTEGER NOT NULL,
    verify_attempted INTEGER NOT NULL,
    verify_failed INTEGER NOT NULL,
    verify_failed_breakdown TEXT NOT NULL,
    verify_succeeded INTEGER NOT NULL,
    verify_succeeded_breakdown TEXT NOT NULL
);
```

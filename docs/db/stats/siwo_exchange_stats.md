# siwo_exchange_stats

Describes how many users are exchanging Sign in with Oseh JWTs for
codes, which is the expected last step after visiting the authorize
page

## Fields

- `id (integer primary key)`: Internal row identifer
- `retrieved_for (text unique not null)`: Primary stable external identifier,
  when the stats are valid for, as of midnight on that date in
  America/Los_Angeles, expressed as `YYYY-MM-DD`
- `retrieved_at (real not null)`: The time that we actually retrieved the
  stats in seconds since the unix epoch.
- `attempted (integer not null)`: how many users requested the exchange
- `failed (integer not null)`: how many exchanges were rejected
- `failed_breakdown (text not null)`: a json object whose keys are integer
  counts and the keys are e.g. `bad_jwt:missing`:
  - `bad_jwt` - the Sign in with Oseh JWT is missing or invalid. details are:
    - `missing` - the JWT is missing
    - `malformed` - could not be interpreted as a JWT
    - `incomplete` - the JWT is missing required claims
    - `signature` - the signature is invalid
    - `bad_iss` - the issuer does not match the expected value
    - `bad_aud` - the audience does not match the expected value
    - `expired` - the JWT is expired
    - `revoked` - the JWT has been revoked
  - `integrity` - the corresponding sign in with oseh identity has been deleted
- `succeeded (integer not null)`: how many exchanges occurred

## Schema

```sql
CREATE TABLE siwo_exchange_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    attempted INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    failed_breakdown TEXT NOT NULL,
    succeeded INTEGER NOT NULL
);
```

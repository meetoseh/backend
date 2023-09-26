# users

Every user who has interacted with our service is represented in one row in this
table.

Typically identified via a JWT in the form of a bearer token in the
authorization header via the sub claim.

## Fields

- `id (integer primary key)`: the internal row identifier
- `sub (text unique not null)`: the sub used for id tokens. Uses the uid prefix
  `u`, see [uid_prefixes](../uid_prefixes.md)
- `email (text not null)`: the email address of the user. NOT A VALID IDENTIFIER.
  Primarily for customer support or contacting them. Is often unique, but there are
  many valid reasons why it may not be. This is set to `anonymous@example.com` when
  they are signing in via Apple but we lost their email address.
- `email_verified (boolean not null)`: if we or an identity provider has confirmed
  that the user owns the email address
- `phone_number (text null)`: the phone number of the user. NOT A VALID IDENTIFIER.
- `phone_number_verified (boolean null)`: if we or an identity provider has confirmed
  that the user owns the phone number.
- `given_name (text null)`: the given name of the user. we don't get this from apple,
  so it's null for apple users unless they specify it
- `family_name (text null)`: the family name of the user
- `admin (boolean not null)`: allows access to the admin panel
- `revenue_cat_id (text unique not null)`: The revenuecat identifier for this user. This
  should be treated as privileged information only accessible by the user and
  admins, unlike the sub. Note that the revenue cat id alone is sufficient for anyone
  to determine the users entitlements and make some modifications, such as uploading
  a new apple receipt for the account. The uid prefix is `u_rc`, see
  [uid_prefixes](../uid_prefixes.md).
- `timezone (text null)`: the users timezone, as an IANA timezone
  (e.g., `America/Los_Angeles`)
- `timezone_technique (text null)`: A hint for how we decided which
  timezone to use for the user. A json object with one of the following
  shapes:

  - `{"style": "migration"}` - We assigned this timezone during the migration
    where we added timezones, setting it to America/Los_Angeles
  - `{"style": "browser"}` - Used the system default timezone on their browser
  - `{"style": "app", "guessed": false}` - Used the system default timezone on
    their phone, i.e., the first non-null timeZone via
    [getCalendars](https://docs.expo.dev/versions/latest/sdk/localization/#localizationgetcalendars).
    For now the app just assumes "America/Los_Angeles" if it cannot get a timezone,
    as timezones are supported by all devices (AFAIK). If it did this, then the
    `guessed` value is true. Otherwise, it is false.

- `created_at (real not null)`: when this record was created in seconds since
  the unix epoch

## Schema

```sql
CREATE TABLE users(
    id INTEGER PRIMARY KEY,
    sub TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    email_verified BOOLEAN NOT NULL,
    phone_number TEXT,
    phone_number_verified BOOLEAN,
    given_name TEXT,
    family_name TEXT,
    admin BOOLEAN NOT NULL,
    revenue_cat_id TEXT UNIQUE NOT NULL,
    timezone TEXT NULL,
    timezone_technique TEXT NULL,
    created_at REAL NOT NULL
);

/* search */
CREATE INDEX users_email_idx ON users(email);
```

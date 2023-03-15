# user_klaviyo_profiles

Describes a users profile in klaviyo:

https://developers.klaviyo.com/en/reference/create_profile

Note:

Currently there are users heldover from the first beta which we purposely are not creating
a klaviyo profile for until they come back to the website. These users can be detected by
e.g.,

```sql
SELECT
  COUNT(*)
FROM users, user_notification_settings
WHERE
  users.id = user_notification_settings.user_id
  AND NOT EXISTS (
    SELECT 1 FROM user_klaviyo_profiles
    WHERE user_klaviyo_profiles.user_id = users.id
  )
```

We should be mindful of this in the following cases:

- For statistics, users without a klaviyo profile do not get added to the
  user notification setting stats
- When creating a klaviyo profile, then, it may require us to update the
  user notification setting stats.

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `ukp`
- `klaviyo_id (text unique not null)`: The identifier of the profile in klaviyo
- `user_id (integer unique not null references users(id) on delete cascade)`: The id of
  the user this klaviyo profile is for
- `email (text not null)`: The users email in klaviyo
- `phone_number (text null)`: The users phone number in klaviyo in E.164 format
- `first_name (text null)`: The users first name in klaviyo
- `last_name (text null)`: The users last name in klaviyo
- `timezone (text not null)`: The users timezone in klaviyo, specified from the
  IANA time zone database (e.g., `America/Los_Angeles`)
- `environment (text not null)`: set in the custom property `environment`, either
  `dev` or `production`
- `created_at (real not null)`: When this record was created, in seconds since the epoch
- `updated_at (real not null)`: The last time we updated this record, in seconds since the epoch

## Schema

```sql
CREATE TABLE user_klaviyo_profiles (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    klaviyo_id TEXT UNIQUE NOT NULL,
    user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    phone_number TEXT NULL,
    first_name TEXT NULL,
    last_name TEXT NULL,
    timezone TEXT NOT NULL,
    environment TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
```

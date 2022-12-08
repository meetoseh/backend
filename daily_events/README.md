# Daily Events

This file describes the overview of how daily events function. Besides the admin
functions, such as creating and searching, users use some endpoint to get a daily
event reference in the form of a JWT, where the sub of the JWT is the uid of the daily
event. They can transform that into a journey JWT for a particular journey in that
daily event.

Daily event JWTs have the following claims

-   is signed using `RS256` using the `OSEH_DAILY_EVENT_JWT_SECRET`
-   the `sub` is the `uid` of the `daily_event`
-   the `oseh:level` is one of:
    -   `read,start_full` - the user has full access to the daily event, i.e., they can
        start a journey in any of the journeys in the daily event. this is the level
        of access achieved via a Pro subscription
    -   `read,start_random` - the user can access most metadata on the journeys within
        the daily event, but they can only start a journey where the server chooses
        the journey for them. this is the level of access achieved without a Pro
        subscription, _before_ starting a journey. the JWT will be revoked when the
        user starts a journey
    -   `read,start_none` - the user can access most metadata on the journeys within
        the daily event, but they cannot start a journey. this is the level of access
        achieved without a Pro subscription, _after_ starting a journey
-   the `aud` is `oseh-daily-events`
-   the `iss` is `oseh`
-   the `jti` is set and the redis key `daily_events:jwt:revoked:{jti}` is not set

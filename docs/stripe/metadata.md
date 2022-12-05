# metadata

Describes metadata we try to keep up to date in stripe. Note that this
is on a best-effort basis and should not be relied upon for critical
functionality.

## Fields

-   `email`: the email address of the user
-   `name`: the name of the user
-   `metadata`: a JSON object containing additional metadata
    -   `user_sub`: the sub of the user in the `users` table
    -   `created_for`: always `start_checkout_stripe`

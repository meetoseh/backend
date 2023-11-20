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
  the user that initiated the merge; i.e., where the identity will be
  transferred to if the merge is successful
- `provider (text not null)`: the provider used; a valid value for
  the column with the same name in `user_identities`. This log entry
  may be written before there is a corresponding record in user_identities
  to reference, so we are essentially referencing it via provider/sub
- `provider_sub (text not null)`: the sub from the provider, acting as
  a unique identifier for the identity the user is attaching
- `operation_uid (text not null)`: an identifier that is stable for
  all of the log entries that were created within effectively the same operation.
  Uses the [uid prefix](../../uid_prefixes.md) `mal_o`
- `phase (text not null)`: one of `initial` or `confirmed`, corresponding to
  if this is the initial merge attempt or we had previously identified a conflict
  and this is
- `step (text not null)`: an enum which is used to identify which step along
  the phase this log entry is for. See the Phases section
- `step_result (text not null)`: an enum whose values depend on the step.
  See the Phases section
- `reason (text not null)`: json object, see [reason](./REASON.md)
- `created_at (real not null)`: when this record was created in seconds since the
  epoch

## Phases

Each step in the underlying phase will include a description of what goes in
the `context` of the `reason`, which it might refer to as just `context`. Similarly,
the `step_result` is just referred to as `result`

### initial

This phase is executed by the client immediately after it parses the merge JWT
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
   - `context`: omitted
2. `create_identity`: Indicates if all we need to do is create a new user identity
   record and then delegate to the standard login with existing identity logic,
   which will handle syncing contact methods and store in the `contact_method_log`
   with `merge_operation_uid` in the context.
   - `result`: always `yes`, as we don't create an entry for this step otherwise
   - `context`: omitted
3. `transfer_identity`: Indicates that the identity exists and is already associated
   with another user on the Oseh platform, so we will need to move the identities,
   contact methods, and history over. This step will also determine if the merge is
   trivial or not. Stripe customers will be copied over as we support more than one
   per user, revenue cat does not have a public endpoint to merge accounts
   (https://community.revenuecat.com/dashboard-tools-52/merge-users-via-dashboard-or-rest-api-1113)

### confirmed

## Schema

# Plausible

We use a special page naming scheme for URLs on plausible. Rather than using the
user-facing URL, which can change for arbitrary reasons, we use the original component
URL for the most relevant component being rendered to the client.

For example, if the user is on a journey share page managed by the
frontend-ssr-web repository using the the component under
`src/routers/journeys/routes/SharedJourney.tsx`, then the page url we send to
plausible will be `/frontend-ssr-web/routers/journeys/routes/SharedJourney.tsx`

This extends easily to the app; we can use the app with plausible by e.g. sending
an event with the url `/frontend-app/user/core/features/requestName/RequestName.tsx`.
Currently we do not do this as we use inapp notifications exclusively for tracking
in-app events, since we need those calls anyway to avoid repeating screens.

Whenever we send events, we keep a client-side list of idempotency tokens for a
short duration to avoid accidentally repeating events. These tokens are often not
random as we don't want to repeat the event twice within the same pageview. The
identifiers used, including random ones, are specified here to avoid conflicts.

[events.md](./events.md) keeps track of all the events that we are currently sending

# Client Flows

Each user has a queue of screens (`client_screens` via `user_client_screens`)
which want to be presented. By convention, we say that front of the queue is the
next screen the user should see, the next is the screen after that, etc, until
the end of the queue.

Clients can only view or remove from the front of the queue. Only when removing
from the front of the queue do they have the option of triggering a client flow
event. From the clients perspective, the queue is never empty: If a client
requests to view the front of their queue, but the queue is empty, this triggers
the `empty` client flow event immediately, which is assumed to have a non-empty
list of screens. If a client encounters a screen that it can't render, then it
removes the screen from the queue using the `skip` client flow event (generally,
`replace: false, screens: []`) until it gets one it can render. The process to
get to a screen the client can handle is sometimes called **screen negotiation**

The backend or jobs server may trigger client flow events at any point, though
typically it is prudent to consider that changes to the queue are not pushed
eagerly to clients. Common times that client flow events are triggered by the
backend would be signing up, merging accounts, etc, where we expect that the
client is going to end their screen (and thus sync) as soon as it receives a
response.

Client flow events are processed always as follows:

1. Optionally, clear the queue. A client flow event either always clears the queue
   at the start of processing, or never clears the queue.

2. Add a list of screens to the queue, starting at the front, in the same order as
   they are listed in the event. The list of screens is always the same and may be
   empty. The screens may be parameterized according to the parameters of the client
   flow event. (EX: if the screens are A, B, C, and the event flow screens are D, E,
   the final screens are D, E, A, B, C).

Client screens take two forms: the form the backend uses (the "unrealized"
form), which may be parameterized by user state (e.g, their name) and may
reference things without jwts and the form the frontend uses (the "realized"
form), which has everything substituted in and JWTs created for all dependencies
(like images). The realized form is generated when the user peeks, and the jwts
can be refreshed by re-peeking.

The client flow paradigm also includes a logging component, which allows seeing
what screens a user has seen and any additional debugging data stored by that
screen. Specifically, when realizing a screen, this creates a new
`user_client_screens_log` record, which can receive
`user_client_screen_actions_log` records. As per the requirement of `*_log`
tables, these are not used for the behavior of the app and thus can be
partitioned or truncated as required.

## Related

### tables

- [client_screens](../../db/client_screens.md)
- [client_flows](../../db/client_flows.md)
- [client_flow_images](../../db/client_flow_images.md)l
- [client_flow_content_files](../../db/client_flow_content_files.md)
- [user_client_screens](../../db/user_client_screens.md)
- [user_client_screens_log](../../db/logs/user_client_screens_log.md)
- [user_client_screen_actions_log](../../db/logs/user_client_screen_actions_log.md)
- [client_flow_stats](../../db/stats/client_flow_stats.md)
- [client_screen_stats](../../db/stats/client_screen_stats.md)

## client endpoints

- `POST /api/1/users/me/screens/pop` - pop [+ trigger client flow] + peek
- `POST /api/1/users/me/screens/trace` - trace
- `POST /api/1/users/me/screens/peek` - peek

## admin endpoints

- `POST /api/1/client_screens/search` - read client screens

Since creating client screens always requires code updates, they are added
or updated via migrations to keep them in sync across environments.

- `POST /api/1/client_flows/search` - read client flows
- `POST /api/1/client_flows/` - create client flow
- `PATCH /api/1/client_flows/` - update client flow
- `DELETE /api/1/client_flows/{uid}` - delete client flow

- `GET /api/1/admin/client_flows/daily_client_flow_stats`
- `GET /api/1/admin/client_flows/daily_client_screen_stats`
- `POST /api/1/admin/log/user_client_screens`
- `POST /api/1/admin/log/user_client_screen_actions`
- `POST /api/1/admin/client_flows/image/` takes processor, length, starts
  file upload
- `POST /api/1/admin/client_flows/image/search` takes list name, returns image refs
- `POST /api/1/admin/client_flows/content/` takes list name, processor, length, starts
  file upload
- `POST /api/1/admin/client_flows/content/search` takes list name, returns content refs
- `POST /api/1/admin/client_flows/test_screen` takes ClientFlowScreen, pushes it to front of queue
- `POST /api/1/admin/client_flows/test_flow` takes flow slug, parameters, peeks with trigger

### jobs

- `runners.stats.daily_client_flow_stats`
- `runners.stats.daily_client_screen_stats`
- `runners.cleanup_old_user_client_screens`

### redis keys

- `stats:client_flows:daily:{unix_date}`
- `stats:client_flows:daily:{unix_date}:extra:{event}`
- `stats:client_flows:daily:earliest`
- `stats:client_screens:daily:{unix_date}`
- `stats:client_screens:daily:{unix_date}:extra:{event}`
- `stats:client_screens:daily:earliest`
- `thumbhashes:{image_uid}:{width}x{height}`

- `ps:stats:client_screens:daily`
- `ps:stats:client_flows:daily`
- `ps:client_flows`
- `ps:client_screens`

### diskcache keys

- `daily_client_flows:{from_unix_date}:{to_unix_date}`
- `daily_client_screens:{from_unix_date}:{to_unix_date}`
- `client_flows:{slug}`
- `client_screens:{slug}`
- `thumbhashes:{image_uid}:{width}x{height}`

### environment variables

- `OSEH_CLIENT_SCREEN_JWT_SECRET`

### additional client flows

signup (for onboarding flows)
merge (for merge)

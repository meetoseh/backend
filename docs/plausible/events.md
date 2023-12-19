# Events

## Pageview

This list starts with the path sent to the pageview event, then the
props for the pageview events, and then all the common events that might
be sent from that page

Template:

- `{path}`
  - {description}
  - pageview props:
    - `{prop1} ({type})`: {description}
  - idempotency: `pageview--{path}`
  - see also:
    - `{event}`

### List

- `frontend-ssr-web/routers/management/routes/ExampleApp.tsx`
  - Used as an example page for server-side rendered components.
  - pageview props:
    - `initialTodos (string)`: a comma-separated list of the initial TODOs
  - idempotency: `pageview--frontend-ssr-web/routers/management/routes/ExampleApp.tsx`
  - see also:
    - `frontend-ssr-web/example/TodoList--add`

## Custom Events

This list starts with the name of the custom event

- `{name}`
  - {description}
  - props:
    - `{prop1} ({type})`: {description}
  - idempotency: {description}

### List

- `frontend-ssr-web/example/TodoList--add`
  - Invoked when a user adds an item to their todo list on ExampleApp
  - props: none
  - idempotency: omitted

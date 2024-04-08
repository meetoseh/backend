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

- `/frontend-ssr-web/routers/management/routes/ExampleApp.tsx`
  - Used as an example page for server-side rendered components.
  - pageview props:
    - `initialTodos (string)`: a comma-separated list of the initial TODOs
  - idempotency: `pageview--frontend-ssr-web/routers/management/routes/ExampleApp.tsx`
  - see also:
    - `frontend-ssr-web/example/TodoList--add`
- `/frontend-ssr-web/routers/journeys/components/SharedUnlockedClassApp.tsx`
  - Used when people directly navigate to the sitemap-included share pages for
    classes, e.g., https://oseh.io/shared/3-part-breath
  - pageview props:
    - `slug (string)`: the slug they navigated to, e.g., `3-part-breath`
    - `instructor (string)`: the name of the instructor
  - idempotency: `pageview--frontend-ssr-web/routers/journeys/components/SharedUnlockedClassApp.tsx`
  - see also:
    - `frontend-ssr-web/uikit/ProvidersList--click`
    - `frontend-ssr-web/uikit/DownloadAppLinks--click`
- `/frontend-ssr-web/routers/journeys/components/ShareLinkApp.tsx`
  - Used when people directly navigate to the sitemap-included share pages for
    classes, e.g., https://oseh.io/shared/3-part-breath
  - pageview props:
    - `title (string)`: the slug they navigated to, e.g., `3 Part Breath`
    - `instructor (string)`: the name of the instructor
    - `code (string)`: the share code they used
  - idempotency: `pageview--frontend-ssr-web/routers/journeys/components/ShareLinkApp.tsx`
  - see also:
    - `frontend-ssr-web/uikit/ProvidersList--click`
    - `frontend-ssr-web/uikit/DownloadAppLinks--click`
- `/frontend-ssr-web/routers/courses/components/CoursePublicPageApp.tsx`
  - Used when people directly navigate to the sitemap-included share pages for
    courses, e.g., https://oseh.io/shared/series/sleep-vibes
  - pageview props:
    - `slug (string)`: the slug they navigated to, e.g., `sleep-vibes`
    - `instructor (string)`: the name of the instructor
  - idempotency: `pageview--frontend-ssr-web/routers/courses/components/CoursePublicPageApp.tsx`
  - see also:
    - `frontend-ssr-web/uikit/ProvidersList--click`
    - `frontend-ssr-web/uikit/DownloadAppLinks--click`

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
- `frontend-ssr-web/uikit/ProvidersList--click`
  - Invoked when the standard uikit providers list (sign in with X buttons)
    has one of its buttons clicked and we are about to redirect
  - props:
    - `provider (string)`: one of `Google`, `SignInWithApple`, `Direct`, `Dev`
  - idempotency: `click--frontend-ssr-web/uikit/ProvidersList`
- `frontend-ssr-web/uikit/DownloadAppLinks--click`
  - Invoked when the standard uikit download app links
    (Download on the App Store, Get it On Google Play) has one of its
    buttons clicked and we are about to redirect
  - props:
    - `provider (string)`: one of `GooglePlay`, `AppleAppStore`
  - idempotency: `click--frontend-ssr-web/uikit/DownloadAppLinks`

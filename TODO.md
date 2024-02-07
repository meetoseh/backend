# Series Changes

This document describes the necessary and remaining changes for the Series update.

## Frontend Changes

These changes MUST be hidden behind a feature-flag `series-released`, unless
otherwise noted. This feature flag MUST require an app release to be changed
(since the payment apis will be disabled until requested via app review)

### Existing screens

#### Homepage

the homepage (pick emotion) screen

- [ ] Bottom Nav: add a bottom nav bar with `Home` highlighted and buttons to
      `Series` and `Account` (settings)

#### Settings

- [ ] Fonts and spacing slightly reworked (not hidden behind feature flag)
- [ ] Account gains `Upgrade to Oseh+` or `Manage Membership` button based on if
      the user is not subscribed to Oseh+ or is subscribed to Oseh+, respectively.
      The `Upgrade to Oseh+` goes to the new upgrade screen (`settings` variant),
      and `Manage Membership` depends on the source of the membership:
  - [ ] stripe links to their customer portal https://stripe.com/docs/no-code/customer-portal
  - [ ] ios / android has a button to cancel membership, which explains where to go
- [ ] Support gains a `Restore Purchases` button which triggers
      https://www.revenuecat.com/docs/restoring-purchases followed by a popup indicating
      success/failure
      https://revenuecat.github.io/react-native-purchases-docs/7.18.0/classes/default.html#restorePurchases

#### Course Activation Screen

- [ ] Update to new backend /courses/activate response format

### New screens

#### Series listing

the main series listing screen, navigated to via the bottom bar in the home screen

- [ ] InfiniteList series in descending order, incorporating the following:
  - [ ] thumbhash background while loading
  - [ ] background image, darkened standard @ 342x427 / 684x854 / 1026x1281 based on dpi
  - [ ] course logo, centered, fixed width 310px, height according to aspect ratio; svg
        includes required spacing if filling 310w is not desired
  - [ ] instructor name
  - [ ] tapping navigates to series preview screen for that series if a video ref is
        available, otherwise straight to the series details page
- [ ] Bottom nav, like in home, series highlighted

#### Series preview

given a single series a screen incorporating the following:

- [ ] background is series intro video;
- [ ] back button upper left which navigates to series listing page
- [ ] closed captioning toggle
- [ ] mute toggle
- [ ] instructor name
- [ ] series name
- [ ] number of classes in series
- [ ] play / pause button in center
- [ ] time progress at bottom
  - [ ] current time
  - [ ] total time
  - [ ] indicator bar
- [ ] seeking
  - [ ] (minimum) tap to seek
  - [ ] (desirable) drag to seek
- [ ] view series button takes you to series details screen

#### Series details screen

- [ ] series title
- [ ] instructor
- [ ] favorite button
- [ ] series description
- [ ] (optional) social proof
- [ ] number of classes
- [ ] (optional) resources
- [ ] unlock button when not an oseh+ member
- [ ] classes listing (finite, eagerly loaded)
  - [ ] background @ 342x133 / 684x266 / 1026x399
  - [ ] title
  - [ ] description
  - [ ] duration
  - [ ] played indicator (checkmark, text next to duration)
  - [ ] tap to play for Oseh+, tap to go to upgrade screen for non-Oseh+
- [ ] (optional) resources

#### Upgrade screen

- [ ] header image @ full width, aspect ratio 390x190
- [ ] oseh+ logo
- [ ] close button, context sensitive (maybe this is a modal rather than a screen)
- [ ] variable title
- [ ] variable value props with icons
- [ ] yearly option, monthly option https://www.revenuecat.com/docs/displaying-products
      https://www.revenuecat.com/reference/get-offerings
      https://revenuecat.github.io/react-native-purchases-docs/7.18.0/classes/default.html#getOfferings
      provides: https://revenuecat.github.io/react-native-purchases-docs/7.18.0/interfaces/PurchasesOfferings.html

      then we go to "current" to get the suggested package

      then we display them, iterating through the packages in order?
      ['weekly', 'monthly', 'twoMonth', 'threeMonth', 'sixMonth', 'annual', 'lifetime']

      request for display in figma: https://meetoseh.slack.com/archives/C029H3HDU6N/p1706898889117869

      each one gives a https://revenuecat.github.io/react-native-purchases-docs/7.18.0/interfaces/PurchasesPackage.html

      which includes https://revenuecat.github.io/react-native-purchases-docs/7.18.0/interfaces/PurchasesStoreProduct.html

      which we need to be able to present:

      - available discounts (cycle / period / priceString)[]
      - intro price (cycles / period / priceString)
      - price and priceString
      - google has subscription options?
      - period in ISO8601, e.g., P1W

- [ ] subscribe button to trigger https://www.revenuecat.com/docs/making-purchases

#### Owned tab in my library (CourseJourneysList)

- [ ] add explicit filter to joined course at neq null

#### Images

- [ ] web support for SVG exports
- [ ] verify app doesn't break when given SVG

## Frontend-SSR changes

### Series share page

`/shared/series/{slug}` acts for courses as `/shared/{slug}` acts for journeys

## Backend API changes

These changes MUST all be backwards-compatible for the app, until at least 1 month
post-update to allow time for rolling updates. To verify this, the api changes
should be made before any client changes and then the app client should be confirmed
to still work without changes.

### Existing

#### /courses/mine

This endpoint is currently unused; it was previously used when users were presented a
popup to continue where they left off on courses.

Should be removed. Current example response:

```json
{
  "courses": [
    {
      "uid": "string",
      "slug": "string",
      "title": "string",
      "title_short": "string",
      "description": "string",
      "background_image": {
        "uid": "string",
        "jwt": "string"
      },
      "circle_image": {
        "uid": "string",
        "jwt": "string"
      }
    }
  ]
}
```

This is using "ExternalCourse", also used in activate course and attach free
course. Activate course is for converting a stripe checkout session to a revenue
cat entitlement and associated attached course, whereas attach free converts a
slug to a revenue cat entitlement and associated attached course (given that the
slug is in a predefined list).

Both are only called on the web client and can be easily adapted to a new
response format: attach_free has its response body completely ignored by the
frontend, and `activate` only needs the background image, title, and visitor
uid.

#### /api/1/users/me/search_course_journeys

This endpoint currently drives the Owned tab of the Library screen
(Favorites/History/Owned), and is a mostly general way of searching
journeys in series, except restricted to journeys in series the user has attached.

This needs to be altered to allow including journeys in series the user
hasn't attached, to accommodate for the new series details page for series
included in Oseh+. The basic way to accomplish this is:

- alter MinimalCourseJourney such that `joined_course_at` is optional, and
  update the docs for `is_next` so it's false if they haven't joined the
  course yet
- alter MinimalCourse to include the series instructor name
- since the client can filter on `joined_course_at neq null` already, no
  additional filters are required to accomodate the current usecase
- since the client can filter on `course_uid` already, no additional filters
  are required to accomodate the new usecase
- for permissions however we are currently using the attachment to know the
  user can see the journey; now we will need to utilize the `flags` added
  to the `courses` table

Additional, minimal course journey needs more information:

- [ ] background image @ 342x133 / 684x266 / 1026x399
- [ ] duration
- [ ] description
- [ ] instructor name

#### /image_files/playlist

- [ ] add support for SVG exports (just tweaking models I think)

### New

#### /courses/search_public

Intended to work both for the series listing page and the owned tab via standard filtering.

Required information for the course:

- [ ] UID
- [ ] Title
- [ ] Description
- [ ] Instructor
- [ ] Favorited yes/no
- [ ] Number of classes
- [ ] Background @ 342x427 / 684x854 / 1026x1281
- [ ] optional Video ref @ fullscreen portrait
- [ ] optional Transcript ref
- [ ] optional video thumbnail @ fullscreen portrait
- [ ] Logo

#### /users/me/get_customer_portal

Returns the stripe customer portal URL for the active stripe customer for the user

## Schema

Describes changes to the format of the database, redis entries, or diskcache entries.
Includes 1-off migrations that are required.

### Existing

#### courses

- [ ] remove circle image file id [ REMEMBER DELETE GUARD ]
- [ ] add optional video content file id [ REMEMBER DELETE GUARD ]
      custom exports for all iphone screen sizes 2020 and newer to get
      maximum hardware acceleration (direct buffer copying), plus standard
      sizes for filling in androids/desktops

  - 430x932
  - 393x852
  - 428x926
  - 390x844
  - 375x667
  - 390x844
  - 375x812

- [ ] add optional video thumbnail image (used while the video is loading, esp
      thumbhash) [ REMEMBER DELETE GUARD ]. if unspecified this will be extracted
      from the video
- [ ] add logo image file id [ REMEMBER DELETE GUARD ]
      we can include an SVG export in `image_file_exports`
- [ ] add instructor
- [ ] remove title short
- [ ] add optional share hero image [ REMEMBER DELETE GUARD ]
- [ ] add flags, basic uint64 enum describing access. this also works
      for soft delete

### New

#### user_course_likes

ability for users to like series rather than just journeys

#### course_background_images

for keeping track of which images were uploaded primarily for
the purpose of a course background; darkened version, original
version

#### course_hero_images

for keeping track of which images were uploaded primarily for
the purpose of a course hero image

#### course_logo_images

for keeping track of which images were uploaded primarily for
the purpose of a course logo image

#### course_video_thumbnail_images

for keeping track of which images were uploaded primarily for
the purpose of acting as the video thumbnail on a course video

should include the content_file_id of the video this was for
and if this was automatically extracted vs uploaded

#### course_videos

for keeping track of which content files were uploaded primarily
for the purpose of a course intro video

#### course_slugs

for keeping track of which slugs go to which series. we'll use
a url convention like oseh.io/shared/series/{slug}

#### course_share_links

Which share links were generated to go to which series

#### course_share_link_views

The views for a given series share link

#### course_share_link_stats

Statistics on share links to series; mostly focused on which techniques
were used to serve them & how successful they were

#### course_share_link_unique_views

Specifically unique views for share links to series; mostly focused on
which users are sharing links and what series they are sharing

### Migrations

#### course circle images

needs to have circle images deleted

#### course background images

needs to have existing course background images re-exported
and added to course_background_images

#### journey background images

needs to have background images re-exported

#### course slugs

initialize slugs for courses

## Admin

basically, should be a way of viewing/creating/modifying series and
corresponding analytics, improve compact journey

### Admin Frontend

#### CompactJourney

Currently compact journeys look like [this](./todo-assets/compact_journey.jpg)

It would be nice if we could have them look like how they will be listed in the
frontend, utilizing the new background exports, on either the
[series details page](./todo-assets/new_compact_journey_opt_a.jpg)
or the
[series public page](./todo-assets/new_compact_journey_opt_b.jpg)
or in
[my library](./todo-assets/new_compact_journey_opt_c.jpg)

notable uses: journey variations, journey feedback, user attribution

#### JourneyBlock

Add link to share page or indicate that the journey is not shareable

#### Series page

Add tab for listing/editing/creating courses.

NOTE for creating - would be ideal if had the option to "create" journeys as
part of the creation of a series, e.g., prepare all the requests and create
at once, utilizing localstorage. all assets (images/video) would be uploaded
eagerly

#### Sharing page

Incorporate sharing series within the page; all numbers should probably just
sum series and journeys values in the highlights, but breakdown the values for
users

### Admin Backend

#### /courses/background_images/

Uploads a series background image

#### /courses/background_images/search

Searches series background images; includes sha512 filter

#### /courses/preview_videos/

Uploads a series preview / introductory video

#### /courses/preview_videos/search

Searches series preview videos; includes sha512 filter

#### /courses/hero_images/

Uploads a series hero image

#### /courses/hero_images/search

Searches series hero images; includes sha512 filter

#### /courses/logo_images/

Uploads a series logo image; prefers SVG or enormous export

#### /courses/logo_images/search

Searches series logo images; includes sha512 filter

#### /journeys/search

Add primary slug, add indicator for whether the journey is shareable

#### /courses/search

Intended for new admin area section on series. We use the simple name for the
admin area for consistency with e.g. journeys, users, vip chat requests, etc.

includes:

- [ ] UID
- [ ] Title
- [ ] Description
- [ ] Instructor
- [ ] Number of classes
- [ ] Background ref
- [ ] Logo ref
- [ ] optional hero image ref
- [ ] optional Share image ref
- [ ] optional Video ref @ fullscreen portrait
- [ ] optional Transcript ref
- [ ] Primary slug / shareable
- [ ] Flags
- [ ] Entitlement
- [ ] Created at

# Phases

This section is intended to describe the required changes in the
order they will be performed.

## 1. Preparation (1-3 days)

- [ ] maintenance
  - [ ] update websocket dependencies (e.g certifi, uvicorn)
  - [ ] update backend dependencies (e.g, certifi, uvicorn)
  - [ ] update job dependencies (e.g., certifi)
  - [ ] update AMIs
- [ ] serving vector-format option for images
  - [ ] `image_files` and `image_file_exports` documentation now explains how svgs work
  - [ ] Images can be served with SVG within playlist
  - [ ] Web frontend checks for SVG, app ignores it
  - [ ] Jobs images handler now includes source SVG in exports if it was rasterized
- [ ] filtering by bit flag field
  - [ ] FilterBitFieldItem
    - [ ] documented as guarranteed to operate against 64-bit twos-complement int.
          example checking for bit 2:
      ```json
      {
        "operator": "bitexpr",
        "mutation": {
          "operator": "and",
          "value": 4
        },
        "comparison": {
          "operator": "neq",
          "value": 0
        }
      }
      ```
    - [ ] optional bitwise operation
      - [ ] "BIT_NOT" ("not") applied via ~a
      - [ ] "BIT_AND" ("and") applied via a&b
      - [ ] "BIT_OR" ("or") applied via a|b
      - [ ] "BIT_XOR" ("xor") applied via (~(a&b))&(a|b)
    - [ ] standard operation
- [ ] include optional transcript for journey audio content endpoint
  - [ ] /journeys/audio_contents/search
- [ ] refactor uploads to support progress indicator, better error messages
  - [ ] redis key `jobs:progress:events:{uid}` goes to array of string json log messages
        associates with the job progress with given uid. always has 24h expiration.
    ```json
    {"type": "queued"|"started"|"bounce"|"progress"|"failed"|"succeeded",
    "message": "string",
    "indicator": {"type": "bar", "at": 3, "of": 7}|{"type": "spinner"}|{"type":"final"}
    }
    ```
  - [ ] redis key `jobs:progress:offset:{uid}` goes to the number indicating the
        real index of the first event in `jobs:progress:events:{uid}`. we keep only
        the last 50 messages in case a job is being spammy. always has 24h expiration
  - [ ] redis key `ps:jobs:progress:{uid}` is published to whenever a new event is
        pushed to the right of `jobs:progress:events`
  - [ ] lib helper function to push message to job progress
  - [ ] lib helper to create and verify job progress JWTs
  - [ ] `/api/2/jobs/{uid}` basic stream of `jobs:progress:events:{uid}`
  - [ ] backend endpoint file_uploads helper includes `FileUploadWithProgressResponse`
  - [ ] /shared/upload/selector/UploadedSelectorContent.tsx new component which accepts a description,
        path, keymap, item component, onClick and calls the click handler when one of the
        items is clicked.
  - [ ] /shared/upload/selector/AudioContentFileChoice.tsx accepts a content
        file ref, optional transcript file ref, and click handler. displays
        the audio content, transcript (click to toggle expanded), and select
        button
  - [ ] /shared/upload/selector/ImageFileChoice.tsx accepts image file ref,
        size & click handler.
  - [ ] /shared/upload/selector/showUploadSelector accepts modals, description,
        path, keymap, item component, returns `CancelablePromise<T | null>`
  - [ ] /shared/upload/selector/createUploadPoller.ts
    ```ts
    (path: string, sha512Key: string = 'original_file_sha512'): (
      (sha512: string) => CancelablePromise<T | null>
    )
    ```
  - [ ] /shared/upload/selector/UploaderContent.tsx new component which accepts
        description, deduplicator/poller by
        `async (sha512: string) => CancelablePromise<T | null>`,
        path to start upload which returns `UploadInfoWithOptionalProgress`, and
        `onUploaded(t: T) => void`
  - [ ] /shared/upload/showUploader accepts modals, description, poller,
        start upload path, onUploaded
  - [ ] journeys now uses showUploader / showUploadSelector
- [ ] update upload jobs to indicate progress
  - [ ] upload journey background image
  - [ ] upload journey audio content
  - [ ] upload instructor picture
- [ ] support video uploads
  - [ ] /shared/upload/selector/VideoContentFileChoice.tsx accepts size,
        content file ref, optional transcript file ref, and click handler.
        displays video, transcript (click to toggle expanded), and select
        button
- [ ] new course access controls
  - [ ] Migration to add flags to courses
    - bit 1: false to prevent the journeys in the series from getting a public
      share page (/shared/{slug})
    - bit 2: false to prevent the journeys in the series from being shared via
      share links (/s/{code})
    - bit 3: false to prevent the series from getting a public share page
      (/shared/series/{slug})
    - bit 4: false to prevent the series from being shared via share links
      (/c/{code})
    - bit 5: false to prevent the series from being shown in the Owned tab
    - bit 6: false to prevent the journeys in the series from being shown in the
      History tab.
    - bit 7: false to prevent the series from being shown in the series listing tab
    - bit 8: false to prevent the journeys in the series from being selected as
      a 1-minute class in emotions
    - bit 9: false to prevent the journeys in the series from being selected as
      a premium class in emotions
    - bit 10: false to prevent the series from being attached without an entitlement
      (/attach_free)
    - bit 11: false to prevent the series from being shown by default in admin series
      listing
  - [ ] /journeys/canonical_url/{uid} respects flags (bit 1)
  - [ ] /shared/{slug} respects flags (bit 1)
  - [ ] /sitemap.xml respects flags (bit 1, later bit 3)
  - [ ] /journeys/check_if_shareable respects flags (bit 2)
  - [ ] /journeys/follow_share_link respects flags (bit 2)
  - [ ] /s/{code} respects flags (bit 2)
  - [x] bit 3 is not relevant yet as at this point series cannot be shared
  - [x] bit 4 is not relevant yet as the series cannot be shared
  - [ ] /users/me/search_course_journeys respects flags (bit 5 for now, bit 7 as well later)
  - [ ] /courses/mine respects flags (bit 5)
  - [ ] /courses/advance respects flags (bit 5)
  - [ ] /courses/start_download respects flags (bit 5)
  - [ ] /courses/start_journey respects flags (bit 5)
  - [ ] /courses/start_next respects flags (bit 5)
  - [ ] /users/me/search_history respects flags (bit 6)
  - [ ] /users/me/start_journey_from_history respects flags (bit 6)
  - [x] bit 7 is not relevant yet as there is no series listing tab
  - [ ] /api/1/emotions/start_related_journey respects flags (bit 8 for now, bit 9 as well later)
  - [ ] /courses/attach_free respects flags (bit 10)
- [ ] remove unnecessary items from frontend-web ExternalCourse parsing
  - [ ] titleShort
  - [ ] circleImage
- [ ] remove unnecessary items from backend ExternalCourse response
  - [ ] title_short
  - [ ] circle_image
- [ ] remove circle image from deletion detection in jobs
- [ ] remove /courses/mine
- [ ] new compact journey format in users, usable in admin
  - [ ] created
  - [ ] used in journey variations
  - [ ] used in journey feedback
  - [ ] used in user attribution
- [ ] update jobs related to journeys to add new export resolutions
  - [ ] manually trigger re-exporting journey background images

## 2. Admin (1-3 days)

- [ ] schema updating course assets, remove unnecessary
  - [ ] course circle images delete job added & manually invoked
  - [ ] migration to remove circle images column from courses
  - [ ] migration to remove title short from courses
  - [ ] migration to add instructor (req) to courses
        each course is assigned the instructor from their first
        journey
  - [ ] migration to add new optional columns to courses
    - [ ] preview content file id
    - [ ] video thumbnail image file id
    - [ ] background image file id
    - [ ] logo image file id
    - [ ] hero image file id
  - [ ] migration to add new tables for series assets
    - [ ] course_videos
    - [ ] course_video_thumbnail_images
    - [ ] course_background_images
    - [ ] course_logo_images
    - [ ] course_hero_images
- [ ] add new assets to deletion guards in jobs
  - [ ] course_videos
  - [ ] course_video_thumbnail_images
  - [ ] course_background_images
  - [ ] course_logo_images
  - [ ] course_hero_images
- [ ] endpoints and jobs for uploading series assets
  - [ ] upload preview content file
    - [ ] sweep job
      - [ ] detects video content files missing thumbnails
      - [ ] detects video content files missing transcripts
      - [ ] runs weekly
    - [ ] job
      - [ ] should extract the first frame and upload it as a video thumbnail image
      - [ ] should extract transcript via whisper and upload it via content_file_transcripts
    - [ ] create endpoint
    - [ ] search endpoint
  - [ ] upload video thumbnail image file
    - [ ] job
    - [ ] create endpoint
    - [ ] search endpoint
      - [ ] includes filter for the preview content file id
  - [ ] upload logo image
    - [ ] job
    - [ ] endpoint
    - [ ] create endpoint
    - [ ] search endpoint
  - [ ] upload hero image
    - [ ] job
    - [ ] endpoint
    - [ ] create endpoint
    - [ ] search endpoint
  - [ ] upload background image
    - [ ] job
    - [ ] endpoint
    - [ ] create endpoint
    - [ ] search endpoint
- [ ] admin series core endpoints
  - [ ] search series
  - [ ] create series
    - [ ] this should not do anything special if the thumbnail image is not
          specified
  - [ ] patch series
    - [ ] updating flags can be thought of as similar to soft deletion
- [ ] admin series core frontend
  - [ ] Series page
    - [ ] Models
      - [ ] CourseBackgroundImage
      - [ ] CourseHeroImage
      - [ ] CourseLogoImage
      - [ ] CoursePreviewContent
      - [ ] CourseVideoThumbnailImage
      - [ ] Course
    - [ ] Block
      - [ ] Loads classes for series
      - [ ] Patchable
    - [ ] FilterAndSort
      - [ ] Filters
        - [ ] Name
        - [ ] Instructor Name
        - [ ] Created At
        - [ ] Flags
        - [ ] UID
      - [ ] Sort
        - [ ] Name
        - [ ] Created At
        - [ ] Instructor Name
    - [ ] Listing
    - [ ] Create
    - [ ] Page Glue

## 3. Series Core (2-4 days)

_unflagged_ = not behind a feature flag, only marked for frontend changes

- [ ] _unflagged_ Owned tab in my library explicitly filters to joined series
- [ ] /api/1/users/me/search_course_journeys updated
  - [ ] model updated for optional `joined_course_at`, including `is_next` docs
  - [ ] if no filter is specified for `joined_course_at` its assumed to be `neq null`,
        for backwards compatibility. use greater than or null 0 as a no-op comparison,
        which we strip if specified for now.
  - [ ] includes course flags bit 7 support
  - [ ] add new fields to series description within journeys
    - [ ] instructor name
  - [ ] add new fields to returned journeys
    - [ ] background image
    - [ ] duration
    - [ ] description
    - [ ] instructor name
- [ ] Add `user_course_likes` model
- [ ] /courses/search_public
- [ ] Series Listing Screen
- [ ] Homepage Bottom Nav
- [ ] Series Preview Screen
- [ ] Series Details Screen

## 4. Upgrade Screen & related (1-2 days)

- [ ] _unflagged_ restyle settings
- [ ] Upgrade Screen
  - [ ] plausible page view
  - [ ] plausible goals documented in backend
  - [ ] plausible goals added via plausible web interface
- [ ] /users/me/get_customer_portal
- [ ] settings: Upgrade / Manage Membership
- [ ] settings: Restore Purchases (native app only)

## 5. Sharing (2-4 days)

- [ ] New tables & documentation
  - [ ] course_slugs
  - [ ] course_share_links
  - [ ] course_share_link_views
  - [ ] course_share_link_stats
  - [ ] course_share_link_unique_views
- [ ] New admin visibility section
  - [ ] don't need to repeat the explanatory flow graph (its the same)
  - [ ] sweep job block (for block stats)
  - [ ] log job block (for block stats)
  - [ ] raced confirmations sweep job block (for block stats)
  - [ ] views chart
  - [ ] unique views chart
- [ ] Update existing admin sharing highlights
  - [ ] /admin/journey_share_links/top_sharers includes series share info
  - [ ] simple top block accepts path as array of string, sums values
  - [ ] Add related highlight endpoints
    - [ ] links created
    - [ ] views
    - [ ] attributable users
    - [ ] unique views
  - [ ] update sharing dashboard to use sums in highlights

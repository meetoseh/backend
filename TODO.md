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

### New screens

#### Series listing

the main series listing screen, navigated to via the bottom bar in the home screen

- [ ] InfiniteList series in descending order, incorporating the following:
  - [ ] thumbhash background while loading
  - [ ] background image, darkened standard @ 342x427 / 684x854 / 1026x1281 based on dpi
  - [ ] course logo, centered, fixed width 310px, height according to aspect ratio; svg
        includes required spacing if filling 310w is not desired
  - [ ] instructor name
  - [ ] tapping navigates to series preview screen for that series
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
- [ ] yearly option, monthly option
- [ ] subscribe button to trigger https://www.revenuecat.com/docs/making-purchases

## Backend changes

TODO

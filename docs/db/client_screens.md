# client_screens

Describes a screen which can be presented at least by some versions of
some clients.

See also: [client flows](../concepts/client_flows/README.md)

## Fields

- `id (integer primary key)`: Internal row identifier
- `uid (text unique not null)`: Primary stable external identifier. Uses the
  [uid prefix](../uid_prefixes.md) `cs`
- `slug (text unique not null)`: The unique identifier for the screen; hard
  coded into the client and stable across environments.
- `name (text not null)`: The human readable name of the screen for the admin
  area
- `description (text not null)`: A description of the screen for the admin area
- `schema (text not null)`: A valid openapi 3.0.3 schema object for the parameters
  to this screen _after_ the flow parameter substitutions but _before_ the screen
  parameter substitutions. https://spec.openapis.org/oas/v3.0.3#schema-object

  MUST have sorted keys with space separators, so it can be exactly reproduced
  with `json.dumps(schema, sort_keys=True)`, in order for admin patch validation to
  work.

  Additional formats are available in this schema, which both describe how the
  admin area should construct the form elements for filling the parameters and
  the specific conversions to get to the final realized parameters provided to
  the client.

  SEE: https://datatracker.ietf.org/doc/html/draft-wright-json-schema-validation-00#section-7

  For string instances (those where `{"type": "string"}`), where `"format"` is included,
  we may add additional specification extensions as defined in
  https://spec.openapis.org/oas/v3.0.3#specification-extensions

  - `image_uid`: the input parameter must be a string, the output parameter is
    `{"uid":"string", "jwt":"string", "thumbhash": "string"}`, where the uid is
    the input parameter, and the jwt is signed for the image with that uid.

    Extension properties:

    - `x-processor`: `{"job": "string", "list": "string"}` corresponds to the job runner
      for processing file uploads targeting this property, and `list` is the list slug
      in `client_flow_images` that the processed images use.
    - `x-thumbhash`: `{ "width\": 0, "height\": 0 }` is the desired width and height
      of the image export whose thumbhash is included inline. The list is sorted by

      ```sql
      min(
        abs(width/height - target_width/target_height)
        abs(height/width - target_height/target_width)
      ) ASC,
      abs(width*height - target_width*target_height) ASC,
      format DESC,
      uid ASC
      ```

    - `x-preview`: `{"width": 0, "height": 0}` corresponds to how the admin area
      should render the attached image for this field in the admin area. This is
      the logical resolution on the client.

    - `x-dynamic-size`:

      ```json
      {
        "width": ["width"],
        "height": ["height"]
      }
      ```

      If specified, the user can specify a dynamic size for this component using
      other parameters on the screen. Specifically, `width` will point to where
      the width of this image can be taken from relative to the screen schema
      root, and `height` will point to where the height of this image can be
      taken from. The processor will be passed this object under the
      `dynamic_size` keyword argument.

      If `x-thumbhash` is not specified but `x-dynamic-size` is, the thumbhash size will
      be the 1x size.

      Typical processing will be 1x, 1.5x, 2x, 2.5x, and 3x, and, for previewing, the smallest of:

      - 1x
      - 200 width, natural height (for large landscape images) (natural meaning 200\*(height/width),
        not using the actual uploaded images aspect ratio)
      - 200 height, natural width (for large portrait images)

      In order to avoid accidental cropping, even widths and heights are generally required.

  - `content_uid`: the input parameter must be a string, the output parameter is

    ```json
    {
      "content": { "uid": "string", "jwt": "string" },
      "transcript": { "uid": "string", "jwt": "string" }
    }
    ```

    Extension properties:

    - `x-processor`: `{"job": "string", "list": "string"}` corresponds to the job runner
      for processing file uploads targeting this property, and `list` is the list slug
      in `client_flow_content_files` that the processed content files use

    - `x-preview`: `{"type": "audio"}` or `{"type": "video", "width": 0, "height": 0}`
      corresponds to how the admin area should render the attached content file for this
      field in the admin area. This is the logical resolution on the client.

  - `journey_uid`: the input parameter must be a string, the output parameter is

    ```json
    {
      "journey": {},
      "last_taken_at": 0,
      "liked_at": 0
    }
    ```

    No extension properties. Always grants the ability to both view and take the journey.

  - `course_uid`: the input parameter must be a string, the output parameter is an
    ExternalCourse. No extension properties.

  - `interactive_prompt_uid`: the input parameter must be a string, the output parameter
    is an ExternalInteractivePrompt. No extension properties.

  - `flow_slug`: does not need to be a trusted input. The output parameter is copied
    from the input parameter. Used as a hint to the admin area that this is going to be
    used for the pop trigger on the screen.

  - `journal_entry_uid`: the input parameter must be a string. The output parameter is
    a journal entry reference (`{"uid": "string", "jwt": "string"}`) which the client
    is expected to use another api call (which will include which journal client key
    they want to use for encryption) to get a journal chat JWT to stream the entries
    contents

  For object instances (those where `{"type": "object"}`), where `"oneOf"` is included,
  we support and require an `x-enum-discriminator` extension property. This is a string
  which will match a required, non-nullable, string property in each `oneOf` object, which
  will have `enum` set to a single unique string. For example, if the `x-enum-discriminator`
  is `type` (a common choice), then the oneof options will all have `type` set to specific,
  unique string.

- `flags (integer not null)`: a bitfield for configuring this screen. The flags are,
  from least significant to most significant bit:

  1. `(decimal: 1)` shows in admin: if not set, this screen is hidden by default
     in the admin area.
  2. `(decimal: 2)` shows on browser: if not set, this screen is skipped in the
     browser, ignoring screen negotiation
  3. `(decimal: 4)` shows on ios: if not set, this screen is skipped on ios,
     ignoring screen negotiation
  4. `(decimal: 8)` shows on android: if not set, this screen is skipped on
     android, ignoring screen negotiation

## Schema

```sql
CREATE TABLE client_screens (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    schema TEXT NOT NULL,
    flags INTEGER NOT NULL
)
```

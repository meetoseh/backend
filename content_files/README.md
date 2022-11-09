# Content Files

This document intends to provide an overview of the how interfacing with content-files
generally works.

Besides the admin-related functions (search, create, etc), users typically get a
content file reference via a JWT signed using the `OSEH_CONTENT_FILE_JWT_SECRET`
with RS256 from the appropriate endpoint (e.g., the journey endpoint). The aud
must be `oseh-content` and the `sub` is the uid of the content file. The `iat`
and `exp` claims are required. The `iss` claim should be `oseh`. The only supported
algorithm is `HS256`.

To convert this jwt to a link to the corresponding export, the client uses
`/api/1/content_files/exports/{uid}/{os}.{ext}`. The `os` and `ext` are
determined by the client. For web, the `os` is `web` and the `ext` is `mp4`.
For android and iOS, the `os` is `android` or `ios` respectively and the
`ext` is `m3u8`. The jwt is provided via the authentication header or
via the `jwt` query parameter.

This allows us to separate the authentication for the content file from
how the content file is served, similarly to if we were using presigned urls
from cloudfront.

Note that the `m3u8` extension requires us dynamically generating the playlist
file with the correct urls. If the `presign` query parameter is set to true,
the playlist will include the JWT in the query parameter for each of the vods,
and then each vod will include the jwt in the part urls. This generally means
caching is not possible, but gives us the broadest possible support.

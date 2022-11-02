# content_file_exports

Describes a single export of an content file. This fixes a particular compression
quality and format. An export can be split into multiple contiguous parts, where
each part can be played independently.

Note that an content file could consist of a sample format (e.g., AAC), a
container format (e.g., MP4), plus adaptive streaming technologies (e.g.,
DASH). For this file, the format will refer to the container format and the
sample format will be part of the codec. The adaptive streaming
technology is typically generated on the fly from supported container formats.

Typically file exports with a single part are used for the web - e.g., a simple
mp4 file. The mp4 file must be constructed in such a way that the browser does
not need to download the entire file before it can start playing. This is known
as a "fast-start" or "web-optimized" build. In our database, it would like like
an content_file_export with the format `mp4` and a single part, also with the
`mp4` format.

For ios, we serve m3u8 files, generated on the fly. The vods would all have
the format `m3u8` where each of the parts would consist of `ts` files. The playlist
file would be constructed from the various content file exports with that format.

See also: [content_file_export_parts](content_file_export_parts.md) for a single
contiguous section of an content file export.

See also: [content_files](content_files.md) for the logical content file, consisting
of one or more exports.

See the example section at the bottom for what m3u8 files look like.

## Fields

-   `id (integer primary key)`: the internal identifier for the row
-   `uid (text unique not null)`: the primary external identifier for the row. The
    uid prefix is `afe`: see [uid_prefixes](../uid_prefixes.md).
-   `content_file_id (integer not null)`: the id of the [content_files](content_files.md)
    row that this export is for
-   `format (text not null)`: the format of the export. Examples: `m4a`, `mp3`, `ogg`
-   `bandwidth (integer not null)`: the maximum bitrate of the export in bits per second.
    Required for client-side adaptive bitrate selection.
-   `codecs (text not null)`: the codecs used in the export, comma separated, for
    example: `avc1.640020,mp4a.40.2`. Required for ios.
-   `target_duration (integer not null)`: the target duration of each part in seconds.
    No part can have a duration larger than this, after flooring. Required for client-side
    preloading.
-   `quality_parameters (text not null)`: a json dictionary describing the quality
    parameters used to generate the export. The keys and values are specific to the
    format. This SHOULD NOT be used for behavior, as it is primarily intended for
    debugging or for one-off scripts (e.g., redoing all exports of a given format/bandwidth
    if we later change the quality parameters).
-   `created_at (real not null)`: when this record was created in seconds since the unix epoch

## Schema

```sql
CREATE TABLE content_file_exports(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    content_file_id INTEGER NOT NULL,
    format TEXT NOT NULL,
    bandwidth INTEGER NOT NULL,
    codecs TEXT NOT NULL,
    target_duration INTEGER NOT NULL,
    quality_parameters TEXT NOT NULL,
    created_at REAL NOT NULL
)

CREATE INDEX content_file_exports_uid ON content_file_exports(uid)
```

## Example m3u8 files

A minimal m3u8 playlist file looks like the following:

```m3u8
#EXTM3U


#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=232370,CODECS="mp4a.40.2, avc1.4d4015"
gear1/prog_index.m3u8

#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=649879,CODECS="mp4a.40.2, avc1.4d401e"
gear2/prog_index.m3u8

#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=991714,CODECS="mp4a.40.2, avc1.4d401e"
gear3/prog_index.m3u8

#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=1927833,CODECS="mp4a.40.2, avc1.4d401f"
gear4/prog_index.m3u8

#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=41457,CODECS="mp4a.40.2"
gear0/prog_index.m3u8
```

Where the corresponding vod files, at minimum, look like the following:

```m3u8
#EXTM3U
#EXT-X-TARGETDURATION:10
#EXT-X-VERSION:3
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:VOD
#EXTINF:9.97667,
fileSequence0.ts
#EXTINF:9.97667,
fileSequence1.ts
/* ..... 178 repetitions skipped ..... */
#EXTINF:4.20333,
fileSequence180.ts
#EXT-X-ENDLIST
```

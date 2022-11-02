# Image Files

Image files behave very similarly to [content files](../content_files/README.md).
Where they differ, image files are simpler: the playlist files act as standard
json endpoints rather than having a specific file extension format. A "playlist"
for an image file consists of all of the exports for that image file.

The client is expected to choose the best available export for the device in the
location they want to render the image. Just as with content files, the playlist
file supports presigning to put the JWT in the query string of the referenced
images.

The JWT for image files is signed with `OSEH_IMAGE_FILE_JWT_SECRET` and has the
audience `oseh-image`, but is otherwise identical to the JWT for content files.

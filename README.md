# Beets Jar

A containerized beets that can help import, tag, and manage a music library via a three pronged approach:

1. Original beets CLI by aliasing `docker exec -it beets-jar beet` to `beet` 
2. A simple front-end user interface
3. A JSON API (Maybe a HATEOAS API if I feel like it)

## Migrating existing library, config, and plugins:
As of beets 2.10.0 item and album art paths are now stored relative to the library path set in the config.yaml, this means you can simply drop in your existing db. You will however have to adjust your existing config to use the default `BEETSDIR` which is `/app/data` and also ensure any other filepaths in the config will be altered to whatever they resolve to within the container.

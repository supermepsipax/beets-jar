# Beets Jar

Crack open a fresh jar of beets!

Beets-Jar is a beets plugin that serves a FastAPI application for those that tire of the terminal. Look at your library, edit your configuration, make decisions for a confused auto-tagger, and (eventually) much, much more!

## Why does this exist?
I originally developed beets jar as a containerized version of beets (hence beets jar) but in early stages of developement I decided to switch to a beets plugin first design that can also be containerized. I feel like this fits in much better with the whole beets ethos that I have grown to love (and not everything needs to be containerized!), plus this way you keep your configuration, plugins, and manage your own dependencies (for better or for worse!)

So that explains the stupid name, but **why** does this exist at all? The main reason comes from me wanting to have more control over beets via HTTP requests. I wanted a way to be able to intiate an import (and even potentially seed that import with extra info to help the auto-tagger), and also have beets communicate the status of the import back to the initiator and perhaps even shuttle user decisions back and forth. This proved to be non-trivial as the import process was very much not asynchronously friendly.

My secondary reasons are:
    1. I like learning and love python and htmx
    2. I want to contribute to beets in some form or another

## Similar Projects
Of course 

## Installation + Use
First install beets jar
```bash
TODO: Install Command
```

Configure your beets configuration:
```yaml
plugins:
  - jar

jar:
 host: 127.0.0.1
 port: 7734
 import_paths:
    - Downloads: /home/user/downloads


```

Start the FastAPI application with:
```bash
beet jar
```

Specify either the host or port number with:
```bash
beet jar --host 127.0.0.1 -p 7734
```

Run as a daemon, Linux + Mac only
```bash
beet jar -D
```

## Current Features
1. A (subjectively) beautiful front end for your beets setup (with light/dark theme)
2. Basic library queries
3. Basic configuration editing + reloading
4. Import via RESTful API
5. User input when autotagger requires intervention

## Planned Features
1. Select, edit, and run plugins on selected library queries
2. More advanced configuration editing (better editor + autocomplete suggestions)
3. Import via API can also communicate choices to the user, and a user's choice to the application
4. Watchable import folder for auto-ingestion
5. File upload + import in browser

## Not Planned Features
1. Music server capabilities (already covered by so many better plugins)
2. Anything not related to stock beets + official plugins.
3. Anything to do with LLMs


## Migrating existing library, config, and plugins:
    NOTE: Only required for container installs 
As of beets 2.10.0 item and album art paths are now stored relative to the library path set in the config.yaml, this means you can simply drop in your existing db. You will however have to adjust your existing config to use the default `BEETSDIR` which is `/app/data` and also ensure any other filepaths in the config will be altered to whatever they resolve to within the container.

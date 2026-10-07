# Beets Jar

Crack open a delicious jar of beets!

Beets-Jar is a beets plugin that serves a FastAPI application for those that tire of the terminal. Manage your library, edit your configuration, make decisions for a confused auto-tagger, initiate and control imports via external applications, and (eventually, maybe) much, much more!

## Why does this exist?
I originally developed beets jar as a containerized version of beets (hence beets jar) but in early stages of development I decided to switch to a beets plugin first design that can also be containerized. I feel like this fits in much better with the whole beets ethos that I have grown to love (and not everything needs to be containerized!), plus this way you keep your configuration, plugins, and manage your own dependencies (for better or for worse!)

So that explains the stupid name, but **why** does this exist at all? The main reason comes from me wanting to have more control over beets via HTTP requests. I wanted a way to be able to initiate an import (and even potentially seed that import with extra info to help the auto-tagger), and also have beets communicate the status of the import back to the initiator and perhaps even shuttle user decisions back and forth. This proved to be non-trivial as the import process was very much not asynchronously friendly.

My secondary reasons are:
    - I like learning and love python and htmx
    - I want to contribute to beets in some form or another

## What I want beets jar to be
I want beets jar to complement the command line but not replace it. I think having a GUI makes beets much more user friendly and a GUI is much more intuitive for certain work flows. I want the setup to be painless as well, which is primarily why I made the containerization as second class citizen.

I also want to minimize the information displayed to the user. I don't like information dense or complex user interfaces so I designed beets jar to be simple and (subjectively) intuitive. I do not intend to bloat this with whatever features I think would be nice, but rather try to achieve parity with the command line for the functions I think are appropriate as well as several features not present in the CLI that come natural to a GUI.

Finally, I want more accessibility, both in terms of user interaction as well as how it is accessed. I've ensured that beets jar is perfectly useable on both desktop/laptops and tablets/phones so you can use it comfortably on almost any device.

## Similar Projects
Since other people have similar projects I want to both acknowledge these applications and state where beets jar is differentiated from them.

- Beets Web, the "official" web plugin for beets, I think the difference here is quite obvious, web is very basic and is more focused on library viewing/playback while jar's primary purpose is import initiation/control.

- Beets Flask, a containerized Flask application that utilizes beets. While I think in general this application could have fit most of my use cases a lot of this application's opinionated aspects coupled with its primary deployment method via containerization makes this project both more complex to setup and you lose easy access to the CLI.

- beetkeeper, I would say similar to Beets Flask but with a greater focus on automation.


## AI Usage
In the age of slop I feel like any project needs to have one of these sections. I have used, and will continue to use LLMs as an assistant in this project. I mainly use them for the less fun things in software development, template generation, refactoring, etc. I make all architectural and design decisions,

## Installation + Use
First install beets jar
```bash
TODO: Install Command
```

beets config:
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

### Running as a systemd service (Linux)
To have beets jar start automatically on boot, create a user service at `~/.config/systemd/user/beet-jar.service`:
```ini
[Unit]
Description=Beets Jar
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%h/.local/bin/beet jar
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```
Adjust `ExecStart` to wherever your `beet` executable lives (check with `which beet`). Don't pass `-D` here, systemd handles running it in the background, or do pass it, I'm not your mother.

Enable and start the service:
```bash
systemctl --user daemon-reload
systemctl --user enable --now beet-jar
```


Check the status and logs with:
```bash
systemctl --user status beet-jar
journalctl --user -u beet-jar -f
```

#### When to restart
Beets loads its plugins once at startup, so restart the service with `systemctl --user restart beet-jar` after:
- Installing, removing, or upgrading beets plugins (or enabling/disabling one in your config)
- Upgrading beets or beets jar
- Changing `host` or `port` in the `jar` config

If you edit the service file itself, run `systemctl --user daemon-reload` before restarting.

## Current Features
1. A (subjectively) beautiful front end for your beets setup (with light/dark theme)
2. Basic library queries
3. More advanced configuration editing (better editor + autocomplete suggestions)
4. Import via RESTful API
5. Select, edit, and run plugins on selected library queries
6. User input when autotagger requires intervention

## Planned Features
1. Import via API can also communicate choices to the user, and a user's choice to the application
2. Watchable import folder for auto-ingestion
3. File upload + import in browser

## Not Planned Features
1. Music server capabilities (already covered by so many better plugins)
2. Anything not related to stock beets + official plugins.
3. Anything to do with LLMs


## Migrating existing library, config, and plugins:
    NOTE: Only required for container installs 
As of beets 2.10.0 item and album art paths are now stored relative to the library path set in the config.yaml, this means you can simply drop in your existing db. You will however have to adjust your existing config to use the default `BEETSDIR` which is `/app/data` and also ensure any other filepaths in the config will be altered to whatever they resolve to within the container.

**UI**
- [x] Find ideal card size for import flow
**Import**
- [x] Basic import w/ user interaction
- [x] Configurable "favorite" paths for quick import
- [ ] Import via file upload in browser
- [ ] Import with seeded context (mbid, album/artist title)
- [ ] Upgrade import for desired bitrate/format
**Configuration**
- [ ] More advanced code editor 
- [ ] Probably checking/reloading jar if plugins are added/removed?
**External API**
- [ ] Trigger import with filepath + extra context 
- [ ] Provide polling information for in progress imports
- [ ] Communicate potential choices between user and beet jar
**Library**
- [x] Basic library query returns list matching query (for album and items)
- [ ] Edit, delete library items
**Plugins**
- [ ] Auto-populate installed plugins and their commands (if any)
- [ ] Use plugins (maybe has to be a manually defined set) on library queries
**Beets Quirks**
- [ ] Beets db is in DELETE mode and maybe should switch to WAL mode
- [ ] Many plugins expect access to stdout for relaying info
**Bugs**
- [ ] Chromium browsers (Helium) keep import page SSE streams open after navigating away (bfcache?), 3 visits = 6 connections = navigation hangs


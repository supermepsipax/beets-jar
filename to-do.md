**UI**
- [x] Find ideal card size for import flow
- [x] Create modal dialogues that can be served with various prompts
**Import**
- [x] Basic import w/ user interaction
- [x] Auto prompt toggle so prompts are pushed to the work area
- [x] Configurable "favorite" paths for quick import
- [ ] Import via file upload in browser
- [x] Import with seeded context (mbid, album/artist title)
- [ ] Upgrade import for desired bitrate/format
**Configuration**
- [x] More advanced code editor 
- [ ] Probably checking/reloading jar if plugins are added/removed?
**External API**
- [x] Authenticated external API for triggering import
- [ ] Trigger import with filepath + extra context 
- [x] Provide polling information for in progress imports
- [ ] Communicate potential choices between user and beet jar
**Library**
- [x] Basic library query returns list matching query (for album and items)
- [x] Delete library items
- [ ] Edit library items
**Plugins**
- [x] Auto-populate installed plugins and their commands (if any)
- [x] Use plugins (maybe has to be a manually defined set) on library queries
**Beets Quirks**
- [ ] Beets db is in DELETE mode and maybe should switch to WAL mode
- [ ] Many plugins expect access to stdout for relaying info
**Bugs**
- [x] Chromium browsers (Helium) keep import page SSE streams open after navigating away (bfcache?), 3 visits = 6 connections = navigation hangs NOTE: This was actually an htmx issue not properly closing out sse streams!


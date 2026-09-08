#!/usr/bin/env python3

import sys
import threading
import logging

from beets.library import Library
from beets import config as beets_config
from beets import plugins as beets_plugins

from app.services import WebImportSession, choose_candidate

log_handler = logging.StreamHandler(sys.stdout)
log_handler.setLevel(logging.DEBUG)
beets_config.read()
beets_plugins.load_plugins()

lib = Library(
    path=beets_config["library"].as_filename(),
    directory=beets_config["directory"].as_filename(),
)

paths = ["/import/downloads/test"]
import_session = WebImportSession(lib=lib,loghandler=log_handler, paths=paths, query=None)
import_session.logger.setLevel(logging.DEBUG)

print("Creating thread")
import_thread = threading.Thread(target=import_session.run)
import_thread.start()

print("Thread created")
while True:
    event = import_session.to_main.get()

    if event["finished"]:
        break

    else:
        choice = choose_candidate(
            event["task"].candidates,
            False,
            event["task"].rec,
            event["task"].cur_artist,
            event["task"].cur_album,
            itemcount=len(event["task"].items),
            choices=event["choices"],
        )

        import_session.to_worker.put(choice)

import_thread.join()

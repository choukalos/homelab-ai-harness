import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from family_kb.config import KB_RAW
from family_kb.ingest_files import ensure_kb_dirs, ingest_existing_raw_files, ingest_source_file


class KBFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        ingest_source_file(Path(event.src_path))

    def on_moved(self, event):
        ingest_source_file(Path(event.dest_path))


def watch_raw_folder() -> None:
    ensure_kb_dirs()
    ingest_existing_raw_files()

    observer = Observer()
    observer.schedule(KBFileHandler(), str(KB_RAW), recursive=True)
    observer.start()

    print(f"Watching {KB_RAW} for files...")

    try:
        while True:
            time.sleep(5)
    finally:
        observer.stop()
        observer.join()



import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from knowledge.family_kb.config import KB_RAW
from knowledge.family_kb.ingest_files import ensure_kb_dirs, ingest_existing_raw_files, ingest_source_file
from knowledge.family_kb.nav_gen import regenerate_all


class KBFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        ingest_source_file(Path(event.src_path))
        # Regenerate indexes after each new file
        regenerate_all()

    def on_moved(self, event):
        ingest_source_file(Path(event.dest_path))
        # Regenerate indexes after each new file
        regenerate_all()


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



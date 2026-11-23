#!/usr/bin/env python3
"""Portal /files/ browse-link regression test.

Background (2026-11-23): the "Potato Wars Trilogy/" folder (name contains
spaces) was unclickable in the /files/video/ listing. render_browse emitted
hrefs with raw, unencoded spaces in *unquoted* HTML attributes:

    <a class=fname href=/files/video/Potato Wars Trilogy/>...

Per the HTML spec an unquoted attribute value ends at the first space, so
browsers parsed href="/files/video/Potato" → click → 404. The fix
percent-encodes every path segment (urllib.parse.quote, safe="") so hrefs
stay valid; this test guards against recurrence.

Run: python3 -m unittest tests.test_portal_browse -v   (from repo root)
"""

import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "portal"))
import server  # noqa: E402


class _HrefCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "href":
                self.hrefs.append(value)


class TestBrowseHrefs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "video" / "Potato Wars Trilogy").mkdir(parents=True)
        (root / "video" / "Potato Wars Trilogy" / "movie_original.mp4").write_bytes(b"x")
        (root / "video" / "plain-file.mp4").write_bytes(b"x")
        self._old_root = server.FILES_ROOT
        server.FILES_ROOT = str(root)
        self.root = root

    def tearDown(self):
        server.FILES_ROOT = self._old_root
        self._tmp.cleanup()

    def _hrefs(self, page: str) -> list:
        collector = _HrefCollector()
        collector.feed(page)
        return collector.hrefs

    def test_no_raw_space_in_any_href(self):
        page = server.render_browse("/files/video/", "video")
        for href in self._hrefs(page):
            self.assertNotIn(" ", href, f"raw space in href: {href!r}")

    def test_folder_href_is_percent_encoded(self):
        page = server.render_browse("/files/video/", "video")
        self.assertIn("/files/video/Potato%20Wars%20Trilogy/", self._hrefs(page))

    def test_file_href_inside_space_folder(self):
        page = server.render_browse("/files/video/Potato%20Wars%20Trilogy/",
                                    "video/Potato Wars Trilogy")
        hrefs = self._hrefs(page)
        self.assertIn("/files/video/Potato%20Wars%20Trilogy/movie_original.mp4", hrefs)
        # breadcrumb back to the parent is a link; the current segment is a
        # <span class=here> (not an href) — assert it renders with the name
        self.assertIn("/files/video/", hrefs)
        self.assertIn('class=here>Potato Wars Trilogy/', page)

    def test_encoded_href_resolves_to_the_directory(self):
        # what a browser requests after decoding the href
        rel = "video/Potato Wars Trilogy"
        self.assertIsNotNone(server.safe_join(server.FILES_ROOT, rel))


if __name__ == "__main__":
    unittest.main(verbosity=2)

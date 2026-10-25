from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.routing import Mount

from app import main


class MediaAccessTests(unittest.TestCase):
    def test_job_ids_must_be_full_random_hex_ids(self) -> None:
        self.assertTrue(main.valid_job_id("a" * 32))
        self.assertFalse(main.valid_job_id("a" * 10))
        self.assertFalse(main.valid_job_id("../" + "a" * 29))

    def test_only_expected_job_media_is_resolvable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previews = root / "previews"
            outputs = root / "outputs"
            job_id = "a" * 32
            job_dir = previews / job_id
            output_dir = outputs / job_id
            job_dir.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            source = job_dir / "source.mp4"
            thumbnail = job_dir / "hook-1.jpg"
            output = output_dir / "short_01.mp4"
            analysis = job_dir / "analysis.json"
            for path in (source, thumbnail, output, analysis):
                path.write_bytes(b"test")

            with patch.object(main, "PREVIEWS", previews), patch.object(main, "OUTPUTS", outputs):
                self.assertEqual(main.media_path(job_id, "source.mp4"), source)
                self.assertEqual(main.media_path(job_id, "hook-1.jpg"), thumbnail)
                self.assertEqual(main.media_path(job_id, "short_01.mp4"), output)
                for filename in ("analysis.json", "../source.mp4", "youtube-cookies.txt", "broll.mp4"):
                    with self.subTest(filename=filename), self.assertRaises(HTTPException):
                        main.media_path(job_id, filename)
                with self.assertRaises(HTTPException):
                    main.media_path("short-id", "source.mp4")

    def test_youtube_url_validation_blocks_non_youtube_and_insecure_urls(self) -> None:
        self.assertTrue(main.is_allowed_youtube_url("https://www.youtube.com/watch?v=abc"))
        self.assertTrue(main.is_allowed_youtube_url("https://youtu.be/abc"))
        for url in (
            "http://youtube.com/watch?v=abc",
            "https://youtube.com.evil.example/watch?v=abc",
            "https://127.0.0.1/admin",
            "https://example.com/video.mp4",
            "https://user:pass@youtube.com/watch?v=abc",
        ):
            with self.subTest(url=url):
                self.assertFalse(main.is_allowed_youtube_url(url))

    def test_data_directory_is_not_mounted_as_a_public_static_directory(self) -> None:
        self.assertFalse(
            any(isinstance(route, Mount) and route.path == "/media" for route in main.app.routes)
        )


if __name__ == "__main__":
    unittest.main()

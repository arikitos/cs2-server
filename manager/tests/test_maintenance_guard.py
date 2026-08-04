from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PANEL = Path(__file__).resolve().parents[1] / "panel"
sys.path.insert(0, str(PANEL))

from maintenance_guard import (  # noqa: E402
    ensure_updater_image,
    gameinfo_has_active_metamod,
    run_updater_container,
)


class FakeNotFound(Exception):
    pass


class FakeDockerException(Exception):
    pass


class FakeImage:
    id = "sha256:local-updater"


class FakeImages:
    def __init__(self, available: bool):
        self.available = available
        self.image = FakeImage()
        self.get_calls = []
        self.build_kwargs = None

    def get(self, reference):
        self.get_calls.append(reference)
        if not self.available:
            raise FakeNotFound(reference)
        return self.image

    def build(self, **kwargs):
        self.build_kwargs = kwargs
        self.available = True
        return self.image, [{"stream": "built updater\n"}]


class FakeUpdaterContainer:
    def __init__(self):
        self.removed = False

    def logs(self, stream=True, follow=True):
        return [b"updater output\n"]

    def wait(self):
        return {"StatusCode": 0}

    def remove(self, force=True):
        self.removed = True


class FakeContainers:
    def __init__(self):
        self.run_image = None
        self.run_kwargs = None
        self.container = FakeUpdaterContainer()

    def get(self, _name):
        raise FakeNotFound()

    def run(self, image, **kwargs):
        self.run_image = image
        self.run_kwargs = kwargs
        return self.container


class FakeJob:
    id = "abc123"

    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class MaintenanceGuardTests(unittest.TestCase):
    def make_panel(self, root: Path, *, available: bool):
        images = FakeImages(available)
        containers = FakeContainers()
        client = types.SimpleNamespace(images=images, containers=containers)
        panel = types.SimpleNamespace(
            CS2_DATA_PATH_HOST="/srv/cs2",
            UPDATER_IMAGE="cs2-manager-updater:pinned",
            PROJECT_DIR=root,
            client=client,
            NotFound=FakeNotFound,
            DockerException=FakeDockerException,
            UPDATER_CONFIRM_PHRASE="UPDATE CS2",
        )
        return panel, images, containers

    def test_existing_local_image_is_reused_without_build(self):
        with tempfile.TemporaryDirectory() as temp:
            panel, images, _containers = self.make_panel(
                Path(temp),
                available=True,
            )
            image = ensure_updater_image(panel, FakeJob())
            self.assertEqual(image.id, "sha256:local-updater")
            self.assertIsNone(images.build_kwargs)

    def test_missing_image_is_built_locally_without_forced_pull(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            updater = root / "updater"
            updater.mkdir()
            (updater / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
            panel, images, _containers = self.make_panel(root, available=False)
            job = FakeJob()

            with patch.dict(
                os.environ,
                {
                    "UPDATER_BUILD_CONTEXT": str(updater),
                    "CS2_BASE_IMAGE": "example/base@sha256:1234",
                },
                clear=False,
            ):
                image = ensure_updater_image(panel, job)

            self.assertEqual(image.id, "sha256:local-updater")
            self.assertEqual(images.build_kwargs["path"], str(updater))
            self.assertEqual(
                images.build_kwargs["tag"],
                "cs2-manager-updater:pinned",
            )
            self.assertFalse(images.build_kwargs["pull"])
            self.assertEqual(
                images.build_kwargs["buildargs"],
                {"CS2_BASE_IMAGE": "example/base@sha256:1234"},
            )
            self.assertTrue(any("missing locally" in row for row in job.messages))

    def test_updater_container_runs_by_local_image_id(self):
        with tempfile.TemporaryDirectory() as temp:
            panel, _images, containers = self.make_panel(
                Path(temp),
                available=True,
            )
            job = FakeJob()
            code = run_updater_container(panel, job, "validate")

            self.assertEqual(code, 0)
            self.assertEqual(containers.run_image, "sha256:local-updater")
            self.assertEqual(
                containers.run_kwargs["environment"]["CS2_UPDATER_MODE"],
                "validate",
            )
            self.assertTrue(containers.container.removed)

    def test_metamod_match_must_be_active_inside_searchpaths(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "gameinfo.gi"
            path.write_text(
                "// Game csgo/addons/metamod\n"
                "FileSystem\n"
                "{\n"
                "    SearchPaths\n"
                "    {\n"
                "        Game csgo\n"
                "    }\n"
                "}\n",
                encoding="utf-8",
            )
            self.assertFalse(gameinfo_has_active_metamod(path))

            path.write_text(
                "FileSystem\n"
                "{\n"
                "    SearchPaths\n"
                "    {\n"
                "        Game csgo/addons/metamod\n"
                "        Game csgo\n"
                "    }\n"
                "}\n",
                encoding="utf-8",
            )
            self.assertTrue(gameinfo_has_active_metamod(path))


if __name__ == "__main__":
    unittest.main()

"""Registry load + lint (P12-B) — green registry, fail-fast on broken."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import registry as regmod

SERVER_ROOT = Path(__file__).resolve().parent.parent
PYDEPS = os.environ.get("FILEBRIDGE_PYDEPS", "")


def _green_doc(tmp_path: Path) -> dict:
    """A green full registry on temp paths (all exist)."""
    root = tmp_path / "media"
    (root / "generated").mkdir(parents=True)
    (root / "public").mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    siri = tmp_path / "siri"
    siri.mkdir()
    nas = tmp_path / "nas"
    (nas / "published").mkdir(parents=True)
    return {
        "public_file_serving": {"root": str(root), "allow": ["generated"]},
        "work_areas": {
            "media_staging": {"path": str(staging)},
            "pipeline_fetch": {"path": str(root / "generated")},
            "siri_outputs": {"path": str(siri), "remote_write": False},
            "nas_media_store": {"path": str(nas), "automount": True,
                                "shared_output": True},
            "matrix_pipeline": {"api": "http://127.0.0.1:9999"},
        },
        "publish_targets": {
            "blog": {"root": str(root / "public"),
                     "subdirs": ["ai", "images"], "default_subdir": "ai",
                     "url_base": "https://choukalos.com/files",
                     "source_roots": [str(root), str(staging)],
                     "size_cap_mb": 500},
            "nas": {"root": str(nas / "published"), "subdirs": [],
                    "url_base": "",
                    "source_roots": [str(root)], "size_cap_mb": 500},
        },
    }


def test_green_registry_no_errors(tmp_path):
    errors, warnings = regmod.lint(_green_doc(tmp_path))
    assert errors == []


def test_missing_sections(tmp_path):
    errors, _ = regmod.lint({})
    joined = " ".join(errors)
    assert "public_file_serving" in joined
    assert "work_areas" in joined
    assert "publish_targets" in joined


def test_work_area_neither_path_nor_api(tmp_path):
    doc = _green_doc(tmp_path)
    doc["work_areas"]["media_staging"] = {"flags": 1}
    errors, _ = regmod.lint(doc)
    assert any("exactly one of path/api" in e for e in errors)


def test_work_area_both_path_and_api(tmp_path):
    doc = _green_doc(tmp_path)
    doc["work_areas"]["media_staging"]["api"] = "http://127.0.0.1:1"
    errors, _ = regmod.lint(doc)
    assert any("exactly one of path/api" in e for e in errors)


def test_work_area_missing_path_error(tmp_path):
    doc = _green_doc(tmp_path)
    doc["work_areas"]["media_staging"] = {"path": str(tmp_path / "nope")}
    errors, _ = regmod.lint(doc)
    assert any("does not exist" in e for e in errors)


def test_work_area_missing_path_automount_warning(tmp_path):
    doc = _green_doc(tmp_path)
    doc["work_areas"]["nas_media_store"]["path"] = str(tmp_path / "not-yet")
    errors, warnings = regmod.lint(doc)
    assert errors == []
    assert any("autofs expected" in w for w in warnings)


def test_work_area_bad_flag_type(tmp_path):
    doc = _green_doc(tmp_path)
    doc["work_areas"]["siri_outputs"]["remote_write"] = "no"
    errors, _ = regmod.lint(doc)
    assert any("must be a boolean" in e for e in errors)


def test_work_area_overlap(tmp_path):
    doc = _green_doc(tmp_path)
    # pipeline_fetch nested under media_staging -> overlap
    doc["work_areas"]["media_staging"]["path"] = str(tmp_path / "media")
    errors, _ = regmod.lint(doc)
    assert any("overlapping paths" in e for e in errors)


def test_target_missing_root(tmp_path):
    doc = _green_doc(tmp_path)
    doc["publish_targets"]["blog"]["root"] = str(tmp_path / "missing")
    errors, _ = regmod.lint(doc)
    assert any("publish_targets.blog.root" in e for e in errors)


def test_target_files_subdir_banned(tmp_path):
    doc = _green_doc(tmp_path)
    doc["publish_targets"]["blog"]["subdirs"] = ["ai", "files"]
    errors, _ = regmod.lint(doc)
    assert any("'files' is banned" in e for e in errors)


def test_target_bad_url_base(tmp_path):
    doc = _green_doc(tmp_path)
    doc["publish_targets"]["blog"]["url_base"] = "choukalos.com/files"
    errors, _ = regmod.lint(doc)
    assert any("url_base" in e for e in errors)


def test_target_missing_source_roots(tmp_path):
    doc = _green_doc(tmp_path)
    del doc["publish_targets"]["blog"]["source_roots"]
    errors, _ = regmod.lint(doc)
    assert any("source_roots" in e for e in errors)


def test_target_bad_size_cap(tmp_path):
    doc = _green_doc(tmp_path)
    doc["publish_targets"]["blog"]["size_cap_mb"] = 0
    errors, _ = regmod.lint(doc)
    assert any("size_cap_mb" in e for e in errors)


def test_d13_siri_not_publicly_served(tmp_path):
    doc = _green_doc(tmp_path)
    doc["public_file_serving"]["allow"] = ["generated", "siri"]
    errors, _ = regmod.lint(doc)
    assert any("D13" in e for e in errors)


def test_load_missing_file(tmp_path):
    assert regmod.load(tmp_path / "absent.yaml") == {}


def _run_cli(policy_file: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["FILEBRIDGE_POLICY"] = str(policy_file)
    if PYDEPS:
        env["PYTHONPATH"] = PYDEPS + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "app.py", "lint"], cwd=SERVER_ROOT, env=env,
        capture_output=True, text=True, timeout=60)


def test_cli_green(tmp_path):
    p = tmp_path / "filebridge.yaml"
    p.write_text(yaml.safe_dump(_green_doc(tmp_path)))
    r = _run_cli(p)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "registry lint: OK" in r.stdout


def test_cli_broken_fails_fast(tmp_path):
    doc = _green_doc(tmp_path)
    doc["work_areas"]["media_staging"] = {"path": str(tmp_path / "nope")}
    p = tmp_path / "filebridge.yaml"
    p.write_text(yaml.safe_dump(doc))
    r = _run_cli(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "registry lint: FAILED" in r.stdout
    assert "does not exist" in r.stdout


def test_real_registry_lint_green():
    """The shipped filebridge.yaml must lint green on this host (thor)."""
    doc = regmod.load(SERVER_ROOT / "filebridge.yaml")
    errors, _ = regmod.lint(doc)
    assert errors == [], errors

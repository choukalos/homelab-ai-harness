#!/usr/bin/env python3
"""YAML validation for the skills system (agents-skills/ + skills/).

Background (2026-09-01): pi.dev failed to parse two SKILL.md frontmatters
because the `description` value contained an unquoted `: ` (colon + space),
which YAML reads as a nested mapping:

    description: Investment brief: portfolio status, ...
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    "Nested mappings are not allowed in compact mappings"

The source-of-truth `skills/<name>/skill.yml` descriptions were quoted (valid),
but the hand-written `agents-skills/<name>/SKILL.md` wrappers lost the quotes.
Fix: reworded both to drop the colon (em dash instead). This test guards
against recurrence and against drift between the two surfaces.

Checks:
  1. Every agents-skills/*/SKILL.md frontmatter parses as strict YAML
     (yaml.safe_load) and has string `name` + non-empty string `description`.
  2. SKILL.md `name` matches its directory name (hyphenated, Agent Skills rule).
  3. Every skills/*/skill.yml parses as YAML and has `name` + `description`.
  4. Cross-check: each agents-skills/<hyphenated> wrapper has a matching
     skills/<underscored>/skill.yml, and the descriptions match exactly
     (catches source/wrapper drift).
  5. Regression: the unquoted-colon pattern from the bug is detected.

Run: python3 -m pytest tests/test_skills_yaml.py -v
Or:  python3 tests/test_skills_yaml.py
Also wired into the pre-commit hook (.githooks/pre-commit).
"""

import os
import re
import unittest

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENTS_SKILLS_DIR = os.path.join(REPO_ROOT, "agents-skills")
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")


def extract_frontmatter(text):
    """Return the YAML frontmatter block of a SKILL.md (between --- markers).

    Raises AssertionError if the file has no frontmatter.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AssertionError("missing frontmatter: file does not start with '---'")
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:i])
    raise AssertionError("missing frontmatter: no closing '---'")


def list_skill_dirs(base):
    return sorted(
        d
        for d in os.listdir(base)
        if os.path.isdir(os.path.join(base, d)) and not d.startswith(".")
    )


class TestSkillMdFrontmatter(unittest.TestCase):
    """Check 1+2: agents-skills/*/SKILL.md frontmatter is strict-parseable YAML."""

    def test_agents_skills_dir_exists(self):
        self.assertTrue(
            os.path.isdir(AGENTS_SKILLS_DIR),
            f"missing {AGENTS_SKILLS_DIR}",
        )

    def test_all_skill_md_frontmatter_parses(self):
        """The exact class of bug that broke pi.dev: frontmatter must be valid YAML.

        yaml.safe_load rejects unquoted `: ` inside a plain scalar with
        'Nested mappings are not allowed in compact mappings'.
        """
        failures = []
        for skill_dir in list_skill_dirs(AGENTS_SKILLS_DIR):
            path = os.path.join(AGENTS_SKILLS_DIR, skill_dir, "SKILL.md")
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                text = f.read()
            try:
                fm = yaml.safe_load(extract_frontmatter(text))
            except AssertionError as e:
                failures.append(f"{skill_dir}: {e}")
                continue
            except yaml.YAMLError as e:
                failures.append(f"{skill_dir}: YAML parse error: {e}")
                continue
            if not isinstance(fm, dict):
                failures.append(f"{skill_dir}: frontmatter is not a mapping")
                continue
            name = fm.get("name")
            description = fm.get("description")
            if not isinstance(name, str) or not name.strip():
                failures.append(f"{skill_dir}: missing/invalid `name`")
            if not isinstance(description, str) or not description.strip():
                failures.append(f"{skill_dir}: missing/invalid `description`")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_skill_md_name_matches_directory(self):
        """Agent Skills rule: `name` is hyphenated and matches the dir name."""
        failures = []
        for skill_dir in list_skill_dirs(AGENTS_SKILLS_DIR):
            path = os.path.join(AGENTS_SKILLS_DIR, skill_dir, "SKILL.md")
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                fm = yaml.safe_load(extract_frontmatter(f.read()))
            if isinstance(fm, dict) and fm.get("name") != skill_dir:
                failures.append(
                    f"{skill_dir}: name={fm.get('name')!r} != directory name"
                )
        self.assertEqual(failures, [], "\n".join(failures))


class TestSkillYmlManifest(unittest.TestCase):
    """Check 3: skills/*/skill.yml manifests are valid YAML with name+description."""

    def test_all_skill_yml_parses(self):
        failures = []
        for skill_dir in list_skill_dirs(SKILLS_DIR):
            path = os.path.join(SKILLS_DIR, skill_dir, "skill.yml")
            if not os.path.isfile(path):
                # TODO placeholders (e.g. code_review) have no manifest — excluded
                # from skill-runner's GET /skills by design.
                continue
            with open(path, encoding="utf-8") as f:
                try:
                    manifest = yaml.safe_load(f.read())
                except yaml.YAMLError as e:
                    failures.append(f"{skill_dir}: YAML parse error: {e}")
                    continue
            if not isinstance(manifest, dict):
                failures.append(f"{skill_dir}: skill.yml is not a mapping")
                continue
            if not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
                failures.append(f"{skill_dir}: missing/invalid `name`")
            if not isinstance(manifest.get("description"), str) or not manifest["description"].strip():
                failures.append(f"{skill_dir}: missing/invalid `description`")
        self.assertEqual(failures, [], "\n".join(failures))


class TestSourceWrapperConsistency(unittest.TestCase):
    """Check 4: SKILL.md wrapper description matches skill.yml source of truth."""

    def test_descriptions_match(self):
        failures = []
        for skill_dir in list_skill_dirs(AGENTS_SKILLS_DIR):
            skill_md = os.path.join(AGENTS_SKILLS_DIR, skill_dir, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue
            # hyphenated wrapper name -> underscored skill dir
            skill_dir_underscored = skill_dir.replace("-", "_")
            skill_yml = os.path.join(SKILLS_DIR, skill_dir_underscored, "skill.yml")
            if not os.path.isfile(skill_yml):
                failures.append(
                    f"{skill_dir}: no skills/{skill_dir_underscored}/skill.yml source"
                )
                continue
            with open(skill_md, encoding="utf-8") as f:
                fm = yaml.safe_load(extract_frontmatter(f.read()))
            with open(skill_yml, encoding="utf-8") as f:
                manifest = yaml.safe_load(f.read())
            if (
                isinstance(fm, dict)
                and isinstance(manifest, dict)
                and fm.get("description") != manifest.get("description")
            ):
                failures.append(
                    f"{skill_dir}: description drift — "
                    f"SKILL.md={fm.get('description')!r} vs "
                    f"skill.yml={manifest.get('description')!r}"
                )
        self.assertEqual(failures, [], "\n".join(failures))


class TestRegressionUnquotedColon(unittest.TestCase):
    """Check 5: the exact bug pattern (unquoted colon+space in description) is caught."""

    def test_unquoted_colon_description_is_rejected(self):
        bad_frontmatter = (
            "name: investment-brief\n"
            "description: Investment brief: portfolio status, dividend highlights.\n"
        )
        with self.assertRaises(yaml.YAMLError):
            yaml.safe_load(bad_frontmatter)

    def test_reworded_em_dash_description_parses(self):
        """The fix pattern: em dash instead of colon, no quotes needed."""
        good_frontmatter = (
            "name: investment-brief\n"
            "description: Investment brief — portfolio status, dividend highlights, "
            "market news. Configurable per user.\n"
        )
        fm = yaml.safe_load(good_frontmatter)
        self.assertIn("description", fm)
        self.assertTrue(re.match(r"^Investment brief —", fm["description"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
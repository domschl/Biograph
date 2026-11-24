from __future__ import annotations

import subprocess
from pathlib import Path

from biograph_sensor_devproject.sensor import (
    build_biograph_event,
    build_wiki_note_event,
    discover_git_repos,
    inspect_notes_dir,
    inspect_repo,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_discover_and_inspect_repo(tmp_path: Path) -> None:
    repo = tmp_path / "intgrad"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Dev")

    (repo / "README.md").write_text(
        "# intgrad\n\nA toy local LLM experimenting with linear recurrence algorithms and integer gradients.\n",
        encoding="utf-8",
    )
    (repo / "model.py").write_text("print('hello')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Add linear recurrence block for toy LLM")

    # Also simulate an uncommitted IDE edit
    (repo / "model.py").write_text("print('recurrence')\n", encoding="utf-8")

    repos = discover_git_repos([tmp_path], max_depth=2)
    assert repos == [repo.resolve()]

    info = inspect_repo(repo, lookback_days=14)
    assert info is not None
    assert info["project"] == "intgrad"
    assert "recurrence" in info["description"].lower()
    assert "Add linear recurrence block for toy LLM" in info["recent_commits"]
    assert "model.py" in info["modified_files"]
    assert "Python" in info["languages"]

    ev = build_biograph_event(info, hostname="workstation")
    assert ev["ev_type"] == "dev-project"
    assert ev["remote_id"].startswith("dev-project:workstation:intgrad:")
    assert "dev" in ev["tags"]


def test_inspect_notes_dir_excludes_private_folders(tmp_path: Path) -> None:
    notes = tmp_path / "Notes"
    (notes / "Science").mkdir(parents=True)
    (notes / "Personal").mkdir(parents=True)
    (notes / "Diary").mkdir(parents=True)

    (notes / "Science" / "Linear Recurrence.md").write_text(
        "---\ntags: [ai]\n---\n# Linear Recurrence\n\nNotes on state-space models and linear recurrence layers in small LLMs.\n",
        encoding="utf-8",
    )
    (notes / "Personal" / "Secret.md").write_text("Private personal note content that must be excluded.", encoding="utf-8")
    (notes / "Diary" / "2026-11-24.md").write_text("Private diary entry that must be excluded.", encoding="utf-8")

    found = inspect_notes_dir(notes, lookback_days=14)
    assert len(found) == 1
    assert found[0]["title"] == "Linear Recurrence"
    assert found[0]["category"] == "Science"

    ev = build_wiki_note_event(found[0], hostname="workstation")
    assert ev["ev_type"] == "wiki-note"
    assert ev["remote_id"].startswith("wiki-note:workstation:")
    assert "science" in ev["tags"]

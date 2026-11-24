"""
Biograph Dev-Project Sensor.

Discovers active local git repositories (detecting both recent git commits and
uncommitted IDE/editor edits), extracts README excerpts, manifest descriptions,
recent commit subjects, and languages, and sends deduplicated `dev-project`
events to the Biograph backend.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import os
import re
import socket
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("biograph_sensor_devproject")

SKIP_DIRS: set[str] = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "target",
    "build",
    "dist",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    "pkg",
    "src_backup",
}

EXT_TO_LANG: dict[str, str] = {
    ".py": "Python",
    ".rs": "Rust",
    ".c": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".h": "C/C++",
    ".hpp": "C++",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".java": "Java",
    ".lua": "Lua",
    ".sh": "Shell",
    ".cu": "CUDA",
    ".qml": "QML",
    ".swift": "Swift",
    ".kt": "Kotlin",
}


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load Biograph TOML config from standard search paths."""
    candidates: list[Path] = []
    if config_path:
        candidates.append(Path(config_path).expanduser())
    env_cfg = os.environ.get("BIOGRAPH_CONFIG")
    if env_cfg:
        candidates.append(Path(env_cfg).expanduser())
    candidates.extend(
        [
            Path("config.toml"),
            Path("~/.config/biograph/config.toml").expanduser(),
            Path("/etc/biograph/config.toml"),
        ]
    )

    for p in candidates:
        if p.is_file():
            try:
                with open(p, "rb") as f:
                    return tomllib.load(f)
            except Exception as err:
                logger.warning("Failed to parse config %s: %s", p, err)
    return {}


def _run_git(repo: Path, args: list[str], timeout: float = 5.0) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout
    except Exception:
        pass
    return ""


def discover_git_repos(roots: list[Path], max_depth: int = 4) -> list[Path]:
    """Find git repositories under root directories up to max_depth."""
    repos: list[Path] = []
    seen: set[Path] = set()

    def _walk(curr: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = list(curr.iterdir())
        except OSError:
            return

        if any(e.name == ".git" for e in entries):
            resolved = curr.resolve()
            if resolved not in seen:
                seen.add(resolved)
                repos.append(resolved)
            return  # Don't recurse inside a git repo (avoid submodules/packaging clones)

        for entry in entries:
            if entry.is_dir() and not entry.is_symlink() and entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                _walk(entry, depth + 1)

    for root in roots:
        expanded = root.expanduser()
        if expanded.is_dir():
            _walk(expanded, 0)

    return sorted(repos)


def _clean_markdown(text: str, max_chars: int = 1800) -> str:
    """Strip markdown images/badges, code blocks, and excess whitespace for compact semantic context."""
    # Remove fenced code blocks
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    # Remove markdown image badges [![...](...)](...) and ![...](...)
    cleaned = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", " ", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", cleaned)
    # Replace markdown links [text](url) with text
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cleaned)
    # Remove HTML tags
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # Collapse whitespace
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in cleaned.splitlines()]
    non_empty = [ln for ln in lines if ln and not set(ln) <= {"-", "=", "#", "*", "_"}]
    joined = "\n".join(non_empty)
    return joined[:max_chars].strip()


def _extract_manifest_description(repo: Path) -> str:
    """Read project description from pyproject.toml, Cargo.toml, or package.json if present."""
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        try:
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            desc = str((data.get("project") or {}).get("description") or "").strip()
            if desc and desc.lower() != "add your description here":
                return desc
        except Exception:
            pass

    cargo = repo / "Cargo.toml"
    if cargo.is_file():
        try:
            with open(cargo, "rb") as f:
                data = tomllib.load(f)
            desc = str((data.get("package") or {}).get("description") or "").strip()
            if desc:
                return desc
        except Exception:
            pass

    pkg_json = repo / "package.json"
    if pkg_json.is_file():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            desc = str(data.get("description") or "").strip()
            if desc:
                return desc
        except Exception:
            pass

    return ""


def _extract_readme(repo: Path) -> tuple[str, str]:
    """Return (first_paragraph_summary, cleaned_excerpt) from README if present."""
    for name in ("README.md", "README.rst", "README.txt", "README", "readme.md"):
        p = repo / name
        if p.is_file():
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")[:12000]
                excerpt = _clean_markdown(raw, max_chars=1800)
                first_para = ""
                for ln in excerpt.splitlines():
                    stripped = ln.lstrip("#> ").strip()
                    if len(stripped) >= 15 and stripped.lower() != repo.name.lower():
                        first_para = stripped[:240]
                        break
                return first_para, excerpt
            except Exception:
                pass
    return "", ""


def _infer_languages(repo: Path) -> list[str]:
    """Infer top programming languages from git-tracked files."""
    out = _run_git(repo, ["ls-files"])
    if not out:
        return []
    counts: dict[str, int] = {}
    for line in out.splitlines()[:2000]:
        ext = Path(line).suffix.lower()
        lang = EXT_TO_LANG.get(ext)
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return [lang for lang, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:4]]


def inspect_repo(
    repo: Path,
    lookback_days: int = 14,
    now_dt: datetime.datetime | None = None,
) -> dict[str, Any] | None:
    """
    Inspect a single git repo. Returns a structured payload dict if the repo has
    recent commits or recent uncommitted IDE/editor edits within lookback_days.
    """
    now = now_dt or datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=lookback_days)

    # 1. Recent commits
    log_out = _run_git(
        repo,
        ["log", f"--since={lookback_days}.days.ago", "--format=%H|%aI|%s", "-n", "12"],
    )
    recent_commits: list[str] = []
    latest_sha = ""
    latest_activity: datetime.datetime | None = None

    for line in log_out.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        sha, iso_str, subject = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not latest_sha:
            latest_sha = sha[:12]
        try:
            dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            if latest_activity is None or dt > latest_activity:
                latest_activity = dt
        except Exception:
            pass
        if subject and subject not in recent_commits:
            recent_commits.append(subject)

    # 2. Uncommitted IDE / editor modifications
    status_out = _run_git(repo, ["status", "--porcelain"])
    modified_files: list[str] = []
    for line in status_out.splitlines():
        if len(line) < 4:
            continue
        rel = line[3:].strip().strip('"')
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1].strip()
        fp = repo / rel
        if fp.is_file():
            try:
                mtime = datetime.datetime.fromtimestamp(fp.stat().st_mtime, tz=datetime.timezone.utc)
                if mtime >= cutoff:
                    modified_files.append(rel)
                    if latest_activity is None or mtime > latest_activity:
                        latest_activity = mtime
            except OSError:
                pass

    if not recent_commits and not modified_files:
        return None

    if not latest_sha:
        head_out = _run_git(repo, ["rev-parse", "--short=12", "HEAD"]).strip()
        latest_sha = head_out or "working-tree"

    readme_para, readme_excerpt = _extract_readme(repo)
    description = _extract_manifest_description(repo) or readme_para
    languages = _infer_languages(repo)

    home_str = str(Path.home())
    repo_str = str(repo)
    portable_path = "~" + repo_str[len(home_str):] if repo_str.startswith(home_str) else repo_str

    activity_ts = latest_activity or now
    fp_raw = f"{latest_sha}|{'|'.join(sorted(modified_files[:10]))}|{activity_ts.date().isoformat()}"
    fingerprint = hashlib.sha1(fp_raw.encode("utf-8")).hexdigest()[:12]

    return {
        "project": repo.name,
        "path": portable_path,
        "description": description,
        "readme_excerpt": readme_excerpt,
        "recent_commits": recent_commits[:10],
        "modified_files": modified_files[:10],
        "latest_commit_sha": latest_sha,
        "languages": languages,
        "timestamp": activity_ts.isoformat(),
        "fingerprint": fingerprint,
    }


def build_biograph_event(info: dict[str, Any], hostname: str) -> dict[str, Any]:
    """Format inspected repo metadata as a Biograph `dev-project` event."""
    project = info["project"]
    desc = info.get("description") or ""
    latest_commit = (info.get("recent_commits") or [""])[0]
    if desc and latest_commit:
        summary = f"Dev project '{project}': {desc[:90]} (latest: {latest_commit[:80]})"
    elif desc:
        summary = f"Dev project '{project}': {desc[:140]}"
    elif latest_commit:
        summary = f"Dev project '{project}': {latest_commit[:140]}"
    else:
        summary = f"Active development on '{project}'"

    tags = ["dev", project.lower()]
    for lang in info.get("languages") or []:
        t = lang.lower().replace("/", "-")
        if t not in tags:
            tags.append(t)

    return {
        "timestamp": info["timestamp"],
        "ev_type": "dev-project",
        "source_host": hostname,
        "source_app": "biograph-sensor-devproject",
        "remote_id": f"dev-project:{hostname}:{project}:{info['fingerprint']}",
        "summary": summary,
        "tags": tags[:6],
        "content": {
            "project": project,
            "path": info["path"],
            "description": desc,
            "readme_excerpt": info.get("readme_excerpt", ""),
            "recent_commits": info.get("recent_commits", []),
            "modified_files": info.get("modified_files", []),
            "latest_commit_sha": info.get("latest_commit_sha", ""),
            "languages": info.get("languages", []),
        },
    }


DEFAULT_NOTES_EXCLUDE_DIRS: set[str] = {
    "personal",
    "diary",
    "templates",
    ".obsidian",
    ".git",
    ".trash",
    "canvas",
}


def _strip_yaml_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text


def inspect_notes_dir(
    notes_dir: Path,
    lookback_days: int = 14,
    exclude_dirs: set[str] | None = None,
    max_notes: int = 15,
    now_dt: datetime.datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Scan a markdown notes/wiki directory (git-controlled or plain filesystem) for
    recently added or modified .md notes within lookback_days.
    Excludes private folders (e.g. Personal, Diary, Templates) by default.
    """
    expanded = notes_dir.expanduser().resolve()
    if not expanded.is_dir():
        return []

    excluded = {d.lower() for d in (exclude_dirs if exclude_dirs is not None else DEFAULT_NOTES_EXCLUDE_DIRS)}
    now = now_dt or datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=lookback_days)

    candidate_files: dict[Path, datetime.datetime] = {}

    # 1. Check git history if notes_dir is inside a git repo
    git_top = _run_git(expanded, ["rev-parse", "--show-toplevel"]).strip()
    if git_top:
        git_root = Path(git_top).resolve()
        log_out = _run_git(
            git_root,
            ["log", f"--since={lookback_days}.days.ago", "--name-only", "--diff-filter=AM", "--format=@@@%aI", "--", "*.md"],
            timeout=8.0,
        )
        curr_dt: datetime.datetime | None = None
        for line in log_out.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("@@@"):
                try:
                    dt = datetime.datetime.fromisoformat(line[3:].replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=datetime.timezone.utc)
                    curr_dt = dt
                except Exception:
                    curr_dt = now
                continue
            if not line.lower().endswith(".md"):
                continue
            fp = (git_root / line).resolve()
            try:
                fp.relative_to(expanded)
            except ValueError:
                continue
            if fp.is_file() and curr_dt is not None:
                if fp not in candidate_files or curr_dt > candidate_files[fp]:
                    candidate_files[fp] = curr_dt

    # 2. Also detect uncommitted / recently edited .md files on disk
    for root, dirs, files in os.walk(expanded):
        dirs[:] = [d for d in dirs if d.lower() not in excluded and not d.startswith(".")]
        for fn in files:
            if not fn.lower().endswith(".md"):
                continue
            fp = (Path(root) / fn).resolve()
            try:
                mtime = datetime.datetime.fromtimestamp(fp.stat().st_mtime, tz=datetime.timezone.utc)
                if mtime >= cutoff:
                    if fp not in candidate_files or mtime > candidate_files[fp]:
                        candidate_files[fp] = mtime
            except OSError:
                pass

    results: list[dict[str, Any]] = []
    home_str = str(Path.home())

    for fp, ts in sorted(candidate_files.items(), key=lambda kv: kv[1], reverse=True):
        try:
            rel = fp.relative_to(expanded)
        except ValueError:
            continue
        if any(part.lower() in excluded or part.startswith(".") for part in rel.parts[:-1]):
            continue
        try:
            raw = fp.read_text(encoding="utf-8", errors="replace")[:10000]
        except OSError:
            continue
        body = _strip_yaml_frontmatter(raw)
        excerpt = _clean_markdown(body, max_chars=1200)
        if len(excerpt) < 20:
            continue

        category = rel.parts[0] if len(rel.parts) > 1 else "Notes"
        title = fp.stem.strip()
        fp_str = str(fp)
        portable_path = "~" + fp_str[len(home_str):] if fp_str.startswith(home_str) else fp_str
        content_hash = hashlib.sha1(excerpt.encode("utf-8")).hexdigest()[:10]
        path_hash = hashlib.sha1(str(rel).encode("utf-8")).hexdigest()[:10]

        results.append(
            {
                "title": title,
                "category": category,
                "rel_path": str(rel),
                "path": portable_path,
                "excerpt": excerpt,
                "timestamp": ts.isoformat(),
                "fingerprint": f"{path_hash}:{content_hash}",
            }
        )
        if len(results) >= max_notes:
            break

    return results


def build_wiki_note_event(info: dict[str, Any], hostname: str) -> dict[str, Any]:
    """Format an active wiki/notes markdown file as a Biograph `wiki-note` event."""
    title = info["title"]
    category = info["category"]
    tags = ["wiki", "note", category.lower()]
    return {
        "timestamp": info["timestamp"],
        "ev_type": "wiki-note",
        "source_host": hostname,
        "source_app": "biograph-sensor-devproject",
        "remote_id": f"wiki-note:{hostname}:{info['fingerprint']}",
        "summary": f"Wiki note ({category}): {title}",
        "tags": list(dict.fromkeys(tags))[:5],
        "content": {
            "title": title,
            "category": category,
            "rel_path": info["rel_path"],
            "path": info["path"],
            "excerpt": info["excerpt"],
        },
    }


def scan_and_send(
    config: dict[str, Any],
    roots_override: list[str] | None = None,
    notes_roots_override: list[str] | None = None,
    lookback_override: int | None = None,
    dry_run: bool = False,
) -> int:
    """Scan configured repo roots and notes directories and send events to Biograph."""
    server_cfg = config.get("server") or {}
    dev_cfg = config.get("devproject") or {}

    base_url = str(server_cfg.get("url", "http://127.0.0.1:8000")).rstrip("/")
    token = str(server_cfg.get("token", ""))
    hostname = str((config.get("cli") or {}).get("source_host") or socket.gethostname())

    raw_roots = roots_override or dev_cfg.get("roots") or ["~/Source", "~/gith", "~/Projects"]
    roots = [Path(r) for r in raw_roots]
    raw_notes = notes_roots_override if notes_roots_override is not None else dev_cfg.get("notes_roots", ["~/Docs/Wiki/Notes"])
    notes_roots = [Path(r) for r in (raw_notes or [])]
    notes_exclude = set(dev_cfg.get("notes_exclude_dirs") or DEFAULT_NOTES_EXCLUDE_DIRS)
    lookback_days = int(lookback_override if lookback_override is not None else dev_cfg.get("lookback_days", 14))
    max_depth = int(dev_cfg.get("max_depth", 4))

    repos = discover_git_repos(roots, max_depth=max_depth)
    events: list[dict[str, Any]] = []
    for repo in repos:
        info = inspect_repo(repo, lookback_days=lookback_days)
        if info:
            events.append(build_biograph_event(info, hostname=hostname))

    dev_count = len(events)
    for ndir in notes_roots:
        note_infos = inspect_notes_dir(ndir, lookback_days=lookback_days, exclude_dirs=notes_exclude)
        for ninfo in note_infos:
            events.append(build_wiki_note_event(ninfo, hostname=hostname))

    wiki_count = len(events) - dev_count
    logger.info(
        "Found %d active dev projects (across %d repos) and %d active wiki notes.",
        dev_count,
        len(repos),
        wiki_count,
    )
    if dry_run or not events:
        for ev in events:
            logger.info("[DryRun] %s", ev["summary"])
        return len(events)

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(f"{base_url}/events/batch", json=events, headers=headers)
        resp.raise_for_status()
        logger.info("Sent %d events (%d dev-project, %d wiki-note) to %s (HTTP %d).", len(events), dev_count, wiki_count, base_url, resp.status_code)
    return len(events)


def main() -> None:
    parser = argparse.ArgumentParser(description="Biograph development project & wiki notes sensor")
    parser.add_argument("-c", "--config", help="Path to Biograph config.toml", default=None)
    parser.add_argument("--roots", nargs="+", help="Override repo root directories to scan", default=None)
    parser.add_argument("--notes-roots", nargs="*", help="Override wiki/notes directories to scan", default=None)
    parser.add_argument("--lookback-days", type=int, default=None, help="Days of git/file activity to consider active")
    parser.add_argument("--once", action="store_true", help="Run a single scan and exit")
    parser.add_argument("--dry-run", action="store_true", help="Scan and log without sending to Biograph")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    interval_min = int((cfg.get("devproject") or {}).get("poll_interval_minutes", 30))

    if args.once or args.dry_run:
        scan_and_send(
            cfg,
            roots_override=args.roots,
            notes_roots_override=args.notes_roots,
            lookback_override=args.lookback_days,
            dry_run=args.dry_run,
        )
        return

    logger.info("Starting Biograph dev-project & wiki notes sensor (interval=%dm)...", interval_min)
    while True:
        try:
            scan_and_send(
                cfg,
                roots_override=args.roots,
                notes_roots_override=args.notes_roots,
                lookback_override=args.lookback_days,
                dry_run=False,
            )
        except Exception as err:
            logger.warning("Dev-project/notes scan failed: %s", err)
        time.sleep(max(60, interval_min * 60))


if __name__ == "__main__":
    main()

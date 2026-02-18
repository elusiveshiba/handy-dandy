#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PR_MERGE_PATTERNS = [
    re.compile(r"^Merge pull request #\d+\b"),
    re.compile(r"\(#\d+\)\s*$"),
]
MERGE_PR_PATTERN = re.compile(r"^Merge pull request #(?P<number>\d+)\b")
SQUASH_PR_PATTERN = re.compile(r"^(?P<title>.+?)\s+\(#(?P<number>\d+)\)\s*$")


def run_git(repo_path, args):
    process = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        stderr = (process.stderr or "").strip() or "unknown git error"
        raise RuntimeError(stderr)
    return (process.stdout or "").strip()


def is_pr_merge_message(subject):
    return any(pattern.search(subject) for pattern in PR_MERGE_PATTERNS)


def extract_pr_details(subject, body):
    merge_match = MERGE_PR_PATTERN.match(subject)
    if merge_match:
        pr_number = merge_match.group("number")
        body_lines = body.splitlines()
        for line in body_lines[1:]:
            clean = line.strip()
            if clean:
                return pr_number, clean
        return pr_number, subject

    squash_match = SQUASH_PR_PATTERN.match(subject)
    if squash_match:
        return squash_match.group("number"), squash_match.group("title").strip()

    return None


def get_repo_name(repo_path):
    top_level = run_git(repo_path, ["rev-parse", "--show-toplevel"])
    return Path(top_level).name


def get_origin_web_url(repo_path):
    try:
        remote_url = run_git(repo_path, ["remote", "get-url", "origin"])
    except RuntimeError:
        return None

    remote_url = remote_url.strip()
    if not remote_url:
        return None

    if remote_url.startswith("git@"):
        match = re.match(r"^git@([^:]+):(.+)$", remote_url)
        if not match:
            return None
        host, path = match.groups()
        clean_path = path[:-4] if path.endswith(".git") else path
        return f"https://{host}/{clean_path}"

    parsed = urlparse(remote_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        clean_path = parsed.path[:-4] if parsed.path.endswith(".git") else parsed.path
        return f"{parsed.scheme}://{parsed.netloc}{clean_path}"

    return None


def parse_origin_slug(origin_web_url):
    if not origin_web_url:
        return None
    parsed = urlparse(origin_web_url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner = parts[0]
    repo = parts[1]
    return owner, repo


def parse_iso_datetime(value):
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def get_ref_timestamp(repo_path, ref_name):
    value = run_git(repo_path, ["log", "-1", "--format=%cI", ref_name])
    return parse_iso_datetime(value)


def fetch_json(url):
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "list-merged-pr-commits",
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def github_merged_prs_between_refs(repo_path, owner, repo, start_ref, end_ref):
    start_ts = get_ref_timestamp(repo_path, start_ref)
    end_ts = get_ref_timestamp(repo_path, end_ref)
    if start_ts > end_ts:
        start_ts, end_ts = end_ts, start_ts

    merged_prs = {}
    page = 1
    max_pages = 20
    while page <= max_pages:
        url = (
            f"https://api.github.com/repos/{owner}/{repo}/pulls"
            f"?state=closed&sort=updated&direction=desc&per_page=100&page={page}"
        )
        pull_requests = fetch_json(url)
        if not pull_requests:
            break

        for pr in pull_requests:
            merged_at = pr.get("merged_at")
            if not merged_at:
                continue
            merged_ts = parse_iso_datetime(merged_at)
            if merged_ts < start_ts or merged_ts > end_ts:
                continue

            pr_number = str(pr.get("number"))
            pr_title = (pr.get("title") or "").strip()
            if pr_number and pr_title:
                merged_prs[pr_number] = pr_title
        page += 1

    return merged_prs


def ensure_tag_exists(repo_path, tag_name):
    process = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/tags/{tag_name}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if process.returncode == 0:
        return

    tag_list = run_git(repo_path, ["tag", "--list", f"*{tag_name}*"])
    if tag_list:
        suggestions = ", ".join(tag_list.splitlines()[:8])
        raise RuntimeError(f"tag not found: {tag_name}. Similar tags: {suggestions}")

    raise RuntimeError(f"tag not found: {tag_name}")


def ensure_commit_exists(repo_path, commit_ref):
    process = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{commit_ref}^{{commit}}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if process.returncode == 0:
        return
    raise RuntimeError(f"commit not found: {commit_ref}")


def sync_tags_from_origin(repo_path):
    remotes_output = run_git(repo_path, ["remote"])
    remotes = [remote.strip() for remote in remotes_output.splitlines() if remote.strip()]
    if not remotes:
        raise RuntimeError("no git remotes configured; cannot sync tags from origin")
    if "origin" not in remotes:
        raise RuntimeError("remote 'origin' not found; cannot sync tags from origin")

    # Force tag refs to mirror origin exactly (required when local tags drift).
    run_git(repo_path, ["fetch", "--prune", "origin", "+refs/tags/*:refs/tags/*"])


def get_merged_pr_messages(repo_path, start_ref, end_ref):
    raw_log = run_git(
        repo_path,
        [
            "log",
            "--pretty=format:%H%x1f%s%x1f%B%x1e",
            f"{start_ref}..{end_ref}",
        ],
    )
    if not raw_log:
        return []

    messages = {}
    records = [record for record in raw_log.split("\x1e") if record.strip()]
    for record in records:
        fields = record.split("\x1f", 2)
        if len(fields) != 3:
            continue
        _, subject, body = fields
        if not is_pr_merge_message(subject):
            continue
        details = extract_pr_details(subject, body)
        if details:
            pr_number, message = details
            messages[pr_number] = message

    return messages


def collect_repo_messages(repo_path, mode, start_ref, end_ref):
    is_git_repo = run_git(repo_path, ["rev-parse", "--is-inside-work-tree"]) == "true"
    if not is_git_repo:
        raise RuntimeError("not a git repository")

    if mode == "tag":
        sync_tags_from_origin(repo_path)
        ensure_tag_exists(repo_path, start_ref)
        ensure_tag_exists(repo_path, end_ref)
        range_start = f"refs/tags/{start_ref}^{{}}"
        range_end = f"refs/tags/{end_ref}^{{}}"
    else:
        ensure_commit_exists(repo_path, start_ref)
        ensure_commit_exists(repo_path, end_ref)
        range_start = start_ref
        range_end = end_ref

    repo_name = get_repo_name(repo_path)
    origin_web_url = get_origin_web_url(repo_path)
    messages = get_merged_pr_messages(repo_path, range_start, range_end)

    slug = parse_origin_slug(origin_web_url)
    if slug:
        owner, repo = slug
        try:
            github_messages = github_merged_prs_between_refs(
                repo_path, owner, repo, range_start, range_end
            )
            for pr_number, pr_title in github_messages.items():
                if pr_number not in messages:
                    messages[pr_number] = pr_title
        except Exception as exc:
            print(f"Warning: GitHub PR lookup failed for {repo_name}: {exc}", file=sys.stderr)

    return repo_name, origin_web_url, messages


def main():
    parser = argparse.ArgumentParser(
        description="List merged PR commit messages between two tags or two commits for one or more repositories."
    )
    parser.add_argument(
        "mode",
        choices=["tag", "commit"],
        help="Range mode: 'tag' uses two tags, 'commit' uses two commits.",
    )
    parser.add_argument(
        "start_ref",
        help="Start tag/commit (older point).",
    )
    parser.add_argument(
        "end_ref",
        help="End tag/commit (newer point).",
    )
    parser.add_argument(
        "repo_paths",
        nargs="+",
        help="One or more paths to git repositories.",
    )
    args = parser.parse_args()

    repo_paths = sorted(
        [os.path.abspath(os.path.expanduser(path)) for path in args.repo_paths],
        key=lambda path: os.path.basename(path).lower(),
    )
    had_error = False

    for idx, repo_path in enumerate(repo_paths):
        if idx > 0:
            print()

        if not os.path.isdir(repo_path):
            print(f"Error: directory does not exist: {repo_path}", file=sys.stderr)
            had_error = True
            continue

        try:
            repo_name, origin_web_url, messages = collect_repo_messages(
                repo_path, args.mode, args.start_ref, args.end_ref
            )
        except RuntimeError as exc:
            print(f"Error: {repo_path}: {exc}", file=sys.stderr)
            had_error = True
            continue

        print(f"Repository: **{repo_name}**")
        for pr_number in sorted(messages, key=lambda n: int(n)):
            message = messages[pr_number]
            safe_message = message.replace('"', '\\"')
            pr_ref = f"#{pr_number}"
            if origin_web_url:
                pr_ref = f"[PR #{pr_number}]({origin_web_url}/pull/{pr_number})"
            print(f'- {pr_ref}: "{safe_message}"')

    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    main()

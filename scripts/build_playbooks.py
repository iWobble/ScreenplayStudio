#!/usr/bin/env python3
"""Put skill folders into a Marvin package file as Playbook blueprints.

    scripts/build_playbooks.py --package docs/screenplay-studio.marvin-package.json skills/screenplay-studio
    scripts/build_playbooks.py --package ../Storyworld/docs/storyworld.marvin-package.json \\
        --slug storyworld --name Storyworld --description "..." ../Storyworld/skills/storyworld-*

Each skill's SKILL.md and its text reference files (references/*.md, .txt, .json, .csv, .yaml) become one `playbook` blueprint named for the
skill. Pictures, scripts and anything else are left out: a Playbook is text only (Marvin refuses the rest), so a skill that needs pictures says
where to find them in the workspace. The package's other blueprints are kept; a Playbook already in it is replaced by the skill's current text,
and the package version is bumped when anything changed (`--version` to set it). A new package file is made if --package does not exist.
"""

import argparse
import json
import re
import sys
from pathlib import Path

TEXT = {".md", ".txt", ".json", ".csv", ".yaml"}
SKIP_DIRS = {"assets", "agents", "scripts"}  # pictures, ChatGPT metadata, code: not Playbook content
LIMITS = {"files": 20, "file": 64 * 1024, "total": 256 * 1024}


def read_skill(folder: Path) -> dict:
    skill = (folder / "SKILL.md").read_text(encoding="utf-8")
    name = re.search(r"^name:\s*(\S+)\s*$", skill, re.M)
    desc = re.search(r"^description:\s*(.+)$", skill, re.M)
    if not name or not desc:
        sys.exit(f"{folder}: SKILL.md needs name: and description: in its frontmatter")
    files = {}
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder)
        if not path.is_file() or rel.name == "SKILL.md" or rel.parts[0] in SKIP_DIRS or path.suffix.lower() not in TEXT:
            continue
        files[rel.as_posix()] = path.read_text(encoding="utf-8")
    sizes = [len(t.encode()) for t in files.values()]
    if len(files) > LIMITS["files"] or any(s > LIMITS["file"] for s in sizes) or len(skill.encode()) + sum(sizes) > LIMITS["total"]:
        sys.exit(f"{folder}: over a Playbook's limits ({LIMITS['files']} files, {LIMITS['file'] // 1024} KB each, {LIMITS['total'] // 1024} KB in all)")
    return {
        "kind": "playbook",
        "slug": name.group(1),
        "name": name.group(1).replace("-", " ").title(),
        "description": desc.group(1).strip()[:500],
        "payload": {"skill_md": skill, "files": files},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--package", required=True, type=Path)
    ap.add_argument("--slug"), ap.add_argument("--name"), ap.add_argument("--description", default=""), ap.add_argument("--version")
    ap.add_argument("skills", nargs="+", type=Path)
    args = ap.parse_args()

    if args.package.exists():
        package = json.loads(args.package.read_text(encoding="utf-8"))
    elif args.slug and args.name:
        package = {"format": 1, "slug": args.slug, "name": args.name, "description": args.description, "version": "0", "blueprints": []}
    else:
        sys.exit(f"{args.package} does not exist: give --slug and --name to make it")

    before = json.dumps(package["blueprints"], sort_keys=True)
    made = {b["slug"]: b for b in map(read_skill, args.skills)}
    kept = [b for b in package["blueprints"] if not (b["kind"] == "playbook" and b["slug"] in made)]
    package["blueprints"] = kept + list(made.values())
    if json.dumps(package["blueprints"], sort_keys=True) != before:
        package["version"] = args.version or str(int(package["version"]) + 1) if str(package["version"]).isdigit() else (args.version or package["version"])
    args.package.write_text(json.dumps(package, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"{args.package}: version {package['version']}, playbooks {', '.join(made)}")


if __name__ == "__main__":
    main()

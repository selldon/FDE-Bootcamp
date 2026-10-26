"""Catch up in the sandbox: put the lab files where they are at the start of a lesson (or after it).

    python sandbox/catchup.py --list          the labs, in course order
    python sandbox/catchup.py 1-7-2           the sandbox as it is when lesson 1-7-2 starts
    python sandbox/catchup.py 1-7-2 --end     ... and as it is after the lesson
    python sandbox/catchup.py 1-7-2 --yes     no question before files are replaced

It only adds and replaces files, it never deletes one. A file of yours that would be replaced is copied first to
sandbox/.backup/<time>/, so nothing you typed is lost.
"""
import filecmp
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
COURSE = HERE / ".course"


def lessons():
    return json.loads((COURSE / "lessons.json").read_text())


def files_of(lesson_id, kind):
    folder = COURSE / lesson_id / kind
    if not folder.exists():
        return {}
    return {p.relative_to(folder).as_posix(): p for p in folder.rglob("*") if p.is_file()}


def wanted(name, after):
    """Every lab file as it is at the start of a lesson: the end of all earlier labs, then this lesson's start."""
    all_lessons = lessons()
    index = next((i for i, l in enumerate(all_lessons) if name in (l["course"], l["id"])), None)
    if index is None:
        sys.exit(f"no lab {name!r}: see python sandbox/catchup.py --list")
    state = {}
    for lesson in all_lessons[:index]:
        state.update(files_of(lesson["id"], "end"))
    this = all_lessons[index]
    state.update(files_of(this["id"], "end" if after else "start"))
    return this, state


def main(args):
    if not args or args[0] == "--list":
        for l in lessons():
            note = "" if l["video"] else "   (given: its files come with the catch-up)"
            print(f"{l['course']:9} {l['title']}{note}")
        return
    this, state = wanted(args[0], "--end" in args)
    new = [name for name in state if not (HERE / name).exists()]
    changed = [name for name in state if (HERE / name).exists() and not filecmp.cmp(state[name], HERE / name, shallow=False)]
    print(f"{this['course']} {this['title']}: {len(new)} files to add, {len(changed)} to replace, "
          f"{len(state) - len(new) - len(changed)} already right")
    if changed:
        for name in changed:
            print("  replace", name)
        if "--yes" not in args and input("Back these up and replace them? [y/N] ").strip().lower() != "y":
            print("nothing changed")
            return
        backup = HERE / ".backup" / time.strftime("%Y%m%d-%H%M%S")
        for name in changed:
            (backup / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(HERE / name, backup / name)
        print("your versions are in", backup.relative_to(HERE.parent))
    for name in new + changed:
        (HERE / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(state[name], HERE / name)
    print("done" if new or changed else "nothing to do")


if __name__ == "__main__":
    main(sys.argv[1:])

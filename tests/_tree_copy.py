"""copy_tree(src, dst, ignore) — shutil.copytree of a LIVE tree, one that other gates write into while it is copied.

The suite runs six gates at once, every one with the worktree as its cwd, and some create a file there and remove it a
moment later (an atomic write's `<path>.tmp.<hex>`). copytree lists a directory and then copies what it listed, so a file
removed in between was an error, and the copying gate went red for another gate's temp file (1.8.9 qualification:
docker_effective_panel and docker_dryrun_writes_nothing, each red once under the six-way suite). What vanished during the
copy is skipped — it is not part of the tree any more; anything still there that failed is still an error."""
import os
import shutil


def copy_tree(src, dst, ignore=None):
    try:
        shutil.copytree(src, dst, ignore=ignore)
    except shutil.Error as e:
        left = [x for x in e.args[0] if os.path.lexists(x[0])]
        if left:
            raise shutil.Error(left)

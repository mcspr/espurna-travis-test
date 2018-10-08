import sys
import time
from subprocess import check_output


def run(cmd, cwd=None):
    out = check_output(cmd, cwd=cwd)
    out = out.decode(sys.getfilesystemencoding()).strip()

    return out


def nightly_tag():
    return time.strftime("%Y%m%d")


def git_head(short=False, cwd=None):
    cmd = ["git", "rev-parse", "HEAD"]
    if short:
        cmd.insert(-1, "--short")
    return run(cmd=cmd, cwd=cwd)


def compare_url(repo, start, end):
    url = "https://github.com/{owner}/{name}/compare/{start}...{end}".format(
        owner=repo.owner, name=repo.name, start=start, end=end
    )
    return url

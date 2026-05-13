from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> int:
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        print(
            "ShellCheck skipped: no local 'shellcheck' executable found on PATH. "
            "Install ShellCheck to enable this lint locally.",
            file=sys.stderr,
        )
        return 0

    cmd = [shellcheck, *sys.argv[1:]]
    completed = subprocess.run(cmd)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

"""Exercise the uploader's Expect listing parser without an SFTP connection."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("count", [2, 60])
def test_remote_listing_preserves_all_entries(tmp_path: Path, count: int) -> None:
    expect = shutil.which("expect")
    if expect is None:
        pytest.skip("expect is required for the uploader regression test")

    source = (Path(__file__).resolve().parents[1] / "scripts/mkweb.sh").read_text()
    procedures = source.split("proc cmd {c} {", 1)[1].split("proc remove {", 1)[0]
    emitter = tmp_path / "listing.py"
    emitter.write_text("""import sys
import time

sys.stdin.readline()
for i in range(int(sys.argv[1])):
    name = f"book_{i:02d}_" + "x" * 170 + ".pdf"
    print(f"-rw-r--r-- 1 owner group 1234 Oct 25 12:00 {name}")
    if i % 5 == 4:
        sys.stdout.flush()
        time.sleep(0.02)
print("sftp> ", end="", flush=True)
""")
    harness = tmp_path / "listing.exp"
    harness.write_text(
        "set timeout 10\n"
        "log_user 0\n"
        "spawn $env(MKWEB_TEST_PYTHON) $env(MKWEB_TEST_EMITTER) "
        "$env(MKWEB_TEST_COUNT)\n"
        "proc cmd {c} {" + procedures + '\nforeach entry [ls_long "."] {\n'
        '    puts "ENTRY:[lindex $entry 1]"\n'
        "}\n"
        "expect eof\n"
        "lassign [wait] pid spawnid os_error status\n"
        "exit $status\n"
    )
    result = subprocess.run(
        [expect, str(harness)],
        env={
            **os.environ,
            "MKWEB_TEST_PYTHON": sys.executable,
            "MKWEB_TEST_EMITTER": str(emitter),
            "MKWEB_TEST_COUNT": str(count),
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    entries = [
        line.removeprefix("ENTRY:")
        for line in result.stdout.splitlines()
        if line.startswith("ENTRY:")
    ]
    assert entries == [f"book_{i:02d}_" + "x" * 170 + ".pdf" for i in range(count)]

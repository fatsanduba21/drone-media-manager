"""Compile the shipped script with Node when available; no browser dependency."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_editorial_javascript_parses(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is optional on the Python server")
    page = (
        Path(__file__).parents[2] / "src/drone_media_manager/api/static/editorial.html"
    )
    script = page.read_text(encoding="utf-8").split("<script>")[1].split("</script>")[0]
    script_file = tmp_path / "editorial.js"
    script_file.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [node, "--check", str(script_file)],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr

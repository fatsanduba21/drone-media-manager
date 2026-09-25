"""Compile the shipped script with Node when available; no browser dependency."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_editorial_javascript_parses() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is optional on the Python server")
    page = (
        Path(__file__).parents[2] / "src/drone_media_manager/api/static/editorial.html"
    )
    script = page.read_text(encoding="utf-8").split("<script>")[1].split("</script>")[0]
    result = subprocess.run(
        [node, "--check"], input=script, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr

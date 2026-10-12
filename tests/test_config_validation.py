import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_configuration_files_pass_validation():
    result = subprocess.run(
        [sys.executable, str(ROOT / "config" / "validate.py"), "--root", str(ROOT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All configuration checks passed" in result.stdout
    assert "soul.example.yaml" in result.stdout.replace("\\", "/")



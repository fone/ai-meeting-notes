"""Packaging contracts for the production Turbo install."""

from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_production_dependencies_use_faster_whisper_without_torch_legacy_whisper():
    requirements = (ROOT / "requirements.txt").read_text()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())

    requirement_lines = [
        line.strip() for line in requirements.splitlines() if line.strip() and not line.startswith("#")
    ]
    dependencies = project["project"]["dependencies"]

    assert any(line.startswith("faster-whisper") for line in requirement_lines)
    assert not any(line.startswith("openai-whisper") for line in requirement_lines)
    assert any(line.startswith("faster-whisper") for line in dependencies)
    assert not any(line.startswith("openai-whisper") for line in dependencies)
    assert project["project"]["optional-dependencies"]["legacy-whisper"] == [
        "openai-whisper>=20231117"
    ]


def test_bootstrap_and_readme_describe_the_production_turbo_path():
    setup = (ROOT / "setup.sh").read_text()
    readme = (ROOT / "README.md").read_text()

    assert "pulseaudio-utils" in setup
    assert "pipewire-bin" in setup
    assert "pw-record" in setup
    assert "turbo" in setup
    assert "--skip-model-download" in setup
    assert "faster-whisper Turbo" in readme
    assert "READY TO RECORD" in readme

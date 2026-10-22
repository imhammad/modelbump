"""Tests for scanning a folder or a file."""

from pathlib import Path

from modelbump.registry import load_registry
from modelbump.scanner import Finding, scan_path


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_scan_folder_finds_ids_in_code_and_config(tmp_path: Path) -> None:
    write(tmp_path, "app/llm.py", 'client.chat.completions.create(model="gpt-3.5-turbo-0613")\n')
    write(tmp_path, "config/models.yaml", "summary_model: claude-3-haiku-20240307\n")
    write(tmp_path, ".env.example", "OPENAI_MODEL=gpt-4o\n")
    write(tmp_path, "README.md", "We use gpt-4o.\n")
    result = scan_path(tmp_path, load_registry())
    assert result.findings == (
        Finding(".env.example", 1, 14, "gpt-4o", None),
        Finding("app/llm.py", 1, 39, "gpt-3.5-turbo-0613", "gpt-3.5-turbo-0613"),
        Finding("config/models.yaml", 1, 16, "claude-3-haiku-20240307", "claude-3-haiku-20240307"),
    )
    assert result.files_scanned == 3
    assert result.files_skipped == 0


def test_scan_single_file_whatever_its_name(tmp_path: Path) -> None:
    write(tmp_path, "notes.md", "default: gpt-4o\n")
    result = scan_path(tmp_path / "notes.md", load_registry())
    assert result.findings == (Finding("notes.md", 1, 10, "gpt-4o", None),)
    assert result.files_scanned == 1


def test_scan_counts_skipped_files(tmp_path: Path) -> None:
    (tmp_path / "weights.json").write_bytes(b"\x00" * 10)
    result = scan_path(tmp_path, load_registry())
    assert result.findings == ()
    assert (result.files_scanned, result.files_skipped) == (0, 1)


def test_scan_maps_cloud_forms_to_the_registry_id(tmp_path: Path) -> None:
    write(tmp_path, "bedrock.py", 'MODEL = "anthropic.claude-3-haiku-20240307-v1:0"\n')
    write(tmp_path, "vertex.py", 'MODEL = "claude-3-5-sonnet@20240620"\n')
    result = scan_path(tmp_path, load_registry())
    assert [(f.model_id, f.registry_id) for f in result.findings] == [
        ("claude-3-haiku-20240307-v1", "claude-3-haiku-20240307"),
        ("claude-3-5-sonnet@20240620", "claude-3-5-sonnet-20240620"),
    ]

from __future__ import annotations

from types import SimpleNamespace

from raganything.processor import ProcessorMixin


class DummyProcessor(ProcessorMixin):
    pass


def test_file_reference_defaults_to_portable_basename():
    processor = DummyProcessor()
    processor.config = SimpleNamespace()

    assert processor._get_file_reference("/data/workspaces/ws/uploads/doc/file.pdf") == "file.pdf"
    assert processor._get_file_reference("https://example.com/file.pdf") == "https://example.com/file.pdf"
    assert processor._get_file_reference("") == "unknown_document"


def test_file_reference_can_keep_full_path():
    processor = DummyProcessor()
    processor.config = SimpleNamespace(citation_full_path=True)

    assert processor._get_file_reference("/data/workspaces/ws/uploads/doc/file.pdf") == "/data/workspaces/ws/uploads/doc/file.pdf"

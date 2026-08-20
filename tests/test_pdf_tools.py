from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zotero_agent_bridge.pdf_tools import extract_pdf_text


class PdfToolsTest(unittest.TestCase):
    def test_pdftotext_output_is_preferred(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="  native text  \n", stderr="")
        with patch("zotero_agent_bridge.pdf_tools.subprocess.run", return_value=completed), patch(
            "zotero_agent_bridge.pdf_tools.PdfReader"
        ) as reader:
            self.assertEqual(extract_pdf_text(Path("paper.pdf")), "native text")
        reader.assert_not_called()

    def test_missing_pdftotext_falls_back_to_pypdf_and_respects_page_limit(self) -> None:
        pages = [
            SimpleNamespace(extract_text=lambda: "page one"),
            SimpleNamespace(extract_text=lambda: "page two"),
            SimpleNamespace(extract_text=lambda: "page three"),
        ]
        with patch("zotero_agent_bridge.pdf_tools.subprocess.run", side_effect=FileNotFoundError), patch(
            "zotero_agent_bridge.pdf_tools.PdfReader",
            return_value=SimpleNamespace(pages=pages),
        ):
            self.assertEqual(extract_pdf_text(Path("paper.pdf"), max_pages=2), "page one\n\npage two")

    def test_failed_extractors_return_empty_text(self) -> None:
        completed = subprocess.CompletedProcess([], 1, stdout="", stderr="failed")
        with patch("zotero_agent_bridge.pdf_tools.subprocess.run", return_value=completed), patch(
            "zotero_agent_bridge.pdf_tools.PdfReader",
            side_effect=ValueError("invalid PDF"),
        ):
            self.assertEqual(extract_pdf_text(Path("paper.pdf")), "")


if __name__ == "__main__":
    unittest.main()

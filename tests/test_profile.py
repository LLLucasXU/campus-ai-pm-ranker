from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from campus_job_ranker.profile import find_resume_candidates, is_supported_resume_source


class ResumeDiscoveryTests(unittest.TestCase):
    def test_ignores_generated_and_hidden_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "resume.pdf").write_bytes(b"pdf")
            (root / "tmp").mkdir()
            (root / "tmp" / "old.pdf").write_bytes(b"pdf")
            (root / ".hidden").mkdir()
            (root / ".hidden" / "secret.pdf").write_bytes(b"pdf")

            self.assertEqual(find_resume_candidates(root), [root / "resume.pdf"])

    def test_prefers_documents_over_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "resume.docx").write_bytes(b"docx")
            (root / "resume-page.png").write_bytes(b"png")

            self.assertEqual(find_resume_candidates(root), [root / "resume.docx"])

    def test_accepts_markdown_and_text_resume_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "resume.md").write_text("简历", encoding="utf-8")

            self.assertEqual(find_resume_candidates(root), [root / "resume.md"])

    def test_explicit_resume_source_requires_a_supported_document_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resume = root / "resume.pdf"
            config = root / "candidate-profile.yaml"
            resume.write_bytes(b"pdf")
            config.write_text("candidate: {}", encoding="utf-8")

            self.assertTrue(is_supported_resume_source(resume))
            self.assertFalse(is_supported_resume_source(config))


if __name__ == "__main__":
    unittest.main()

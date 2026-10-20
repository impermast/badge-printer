"""Small end-to-end checks; run with python -m unittest discover -s tests."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import fitz

from settings import Paths
from scripts.ai_patches import export_ai, import_ai
from scripts.generate import generate_pdf
from scripts.prepare import apply_approved, prepare, shorten, transliterate
from scripts.records import AFFILIATION_COLUMNS, read_csv, save_csv


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        from main import CONFIG
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        original = CONFIG.paths
        paths = replace(
            original,
            root=root,
            registrations=root / "input.csv",
            participants=root / "participants.csv",
            dictionary=root / "dictionary.csv",
            affiliation_review=root / "affiliations_review.csv",
            review_html=root / "review.html",
            patches=root / "patches",
            pdf_output=root / "badges.pdf",
        )
        shutil.copy2(original.dictionary, paths.dictionary)
        self.settings = replace(CONFIG, paths=paths)
        shutil.copy2(original.root / "data/examples/registrations_demo.csv", paths.registrations)

    def test_two_pipelines_with_human_approval(self):
        config = self.settings
        prepare(config)
        people = read_csv(config.paths.participants)
        self.assertEqual(len(people), 4)
        self.assertEqual(people[0]["Full Name"], "Пётр Тетерин")
        self.assertEqual(people[0]["Last Name"], "Teterin")
        self.assertEqual(people[1]["Institution"], "MSU / JINR")
        self.assertEqual(people[2]["Review"], "NEED REVIEW")

        export_ai(config)
        batch_path = config.paths.patches / "original/batch_001.json"
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        self.assertEqual(len(batch["items"]), 1)
        self.assertNotIn("ID", json.dumps(batch))  # Privacy: no participant details.
        batch["items"][0]["suggested"] = "UAPR"
        batch["items"][0]["notes"] = "Test-only fictional abbreviation"
        destination = config.paths.patches / "returned/batch_001.json"
        destination.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
        import_ai(config)
        pending = read_csv(config.paths.affiliation_review)
        self.assertEqual(pending[0]["Suggested"], "UAPR")
        self.assertEqual(pending[0]["Approved"], "")
        pending[0]["Approved"] = "YES"
        save_csv(config.paths.affiliation_review, pending, AFFILIATION_COLUMNS)
        apply_approved(config)
        people = read_csv(config.paths.participants)
        self.assertEqual(people[2]["Institution"], "UAPR")
        self.assertEqual(people[2]["Review"], "OK")

        people[1]["Type"] = "ORGANIZER"
        save_csv(config.paths.participants, people)
        generate_pdf(config)
        with fitz.open(config.paths.pdf_output) as doc:
            self.assertEqual(len(doc), 1)
            self.assertAlmostEqual(doc[0].rect.width, 210 * 72 / 25.4, delta=0.01)
            text = doc[0].get_text()
            self.assertIn("Pyotr", text)
            self.assertIn("UAPR", text)

    def test_reject_incomplete_or_modified_batches(self):
        config = self.settings
        prepare(config)
        export_ai(config)
        batch = json.loads((config.paths.patches / "original/batch_001.json").read_text())
        batch["items"][0]["affiliation"] = "Changed original"
        (config.paths.patches / "returned/batch_001.json").write_text(json.dumps(batch))
        with self.assertRaisesRegex(ValueError, "Affiliations changed"):
            import_ai(config)

    def test_manual_file_not_overwritten(self):
        config = self.settings
        prepare(config)
        rows = read_csv(config.paths.participants)
        rows[0]["First Name"] = "Petr"
        save_csv(config.paths.participants, rows)
        with self.assertRaisesRegex(ValueError, "already exists"):
            prepare(config)
        self.assertEqual(read_csv(config.paths.participants)[0]["First Name"], "Petr")

    def test_dictionary_does_not_guess_on_commas(self):
        mapping = {"a": "A", "b": "B"}
        self.assertEqual(shorten("A, B", mapping), ("A / B", True))
        self.assertEqual(shorten("A, University, Moscow", mapping), ("A, University, Moscow", False))
        self.assertEqual(transliterate("Фёдор"), "Fyodor")


if __name__ == "__main__":
    unittest.main()

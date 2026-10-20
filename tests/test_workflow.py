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
from scripts.layout import find_font, name_lines
from scripts.prepare import apply_approved, prepare, shorten, transliterate
from scripts.records import AFFILIATION_COLUMNS, AFFILIATION_TOO_LONG, NO_AFFILIATION, read_csv, save_csv


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
            patches=root / "ai-patches",
            pdf_output=root / "badges.pdf",
            participant_design=original.root / "design/test_participant.png",
            organizer_design=original.root / "design/test_organizer.png",
        )
        shutil.copy2(original.dictionary, paths.dictionary)
        self.settings = replace(CONFIG, paths=paths)
        shutil.copy2(original.root / "data/examples/registrations_demo.csv", paths.registrations)

    def test_two_pipelines_with_human_approval(self):
        config = self.settings
        prepare(config)
        people = read_csv(config.paths.participants)
        self.assertEqual(len(people), 4)
        self.assertEqual(people[0]["Full Name"], "Alfa Beta Gama Delta")
        self.assertEqual(people[0]["Last Name"], "Delta")
        self.assertEqual(people[1]["Institution"], "MSU / JINR")
        self.assertEqual(people[2]["Review"], "NEED REVIEW")

        dictionary_before_export = config.paths.dictionary.read_bytes()
        export_ai(config)
        reference = config.paths.patches / "affiliations_reference.csv"
        self.assertEqual(reference.read_bytes(), dictionary_before_export)
        instructions = (config.paths.patches / "INSTRUCTIONS.md").read_text(encoding="utf-8")
        self.assertIn("affiliations_reference.csv", instructions)
        self.assertIn("альтернативные написания", instructions)
        self.assertEqual(config.paths.dictionary.read_bytes(), dictionary_before_export)
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
        dictionary = read_csv(config.paths.dictionary)
        self.assertIn({"Affiliation": "Lomonosov Moscow State University", "Institution": "MSU"}, dictionary)
        self.assertIn({"Affiliation": "Unknown University of Advanced Physical Research", "Institution": "UAPR"}, dictionary)

        people[1]["Type"] = "ORGANIZER"
        save_csv(config.paths.participants, people)
        generate_pdf(config)
        with fitz.open(config.paths.pdf_output) as doc:
            self.assertEqual(len(doc), 1)
            self.assertAlmostEqual(doc[0].rect.width, 210 * 72 / 25.4, delta=0.01)
            text = doc[0].get_text()
            self.assertIn("Alfa", text)
            self.assertIn("UAPR", text)

    def test_blank_ai_suggestion_can_be_resolved_manually(self):
        config = self.settings
        prepare(config)
        export_ai(config)
        batch_path = config.paths.patches / "original/batch_001.json"
        returned = config.paths.patches / "returned/batch_001.json"
        returned.write_bytes(batch_path.read_bytes())  # AI found no verified abbreviation.
        import_ai(config)
        review = read_csv(config.paths.affiliation_review)
        self.assertEqual(review[0]["Suggested"], "")
        review[0]["Suggested"] = "UAPR"
        review[0]["Approved"] = "YES"
        save_csv(config.paths.affiliation_review, review, AFFILIATION_COLUMNS)
        apply_approved(config)
        edited = read_csv(config.paths.participants)
        self.assertEqual(edited[2]["Institution"], "UAPR")
        self.assertEqual(edited[2]["Review"], "OK")
        self.assertIn("UAPR", config.paths.dictionary.read_text(encoding="utf-8"))

    def test_too_long_affiliation_never_breaks_batch(self):
        config = self.settings
        source = read_csv(config.paths.registrations)
        source[0]["Affiliation"] = "Federal State Educational Institution of Higher " * 5
        save_csv(config.paths.registrations, source, tuple(source[0]))
        prepare(config)
        people = read_csv(config.paths.participants)
        self.assertIn(AFFILIATION_TOO_LONG, people[0]["Notes"])
        self.assertEqual(people[0]["Review"], "NEED REVIEW")

        generate_pdf(config)
        with fitz.open(config.paths.pdf_output) as doc:
            self.assertEqual(len(doc), 1)
            text = doc[0].get_text()
            self.assertIn(people[0]["Last Name"], text)
            self.assertNotIn("Federal State Educational", text)

        # Once manually shortened, the stale length flag disappears.
        people = read_csv(config.paths.participants)
        people[0]["Institution"] = "FSEI"
        people[0]["Review"] = "OK"
        people[0]["Notes"] = AFFILIATION_TOO_LONG
        save_csv(config.paths.participants, people)
        generate_pdf(config)
        revised = read_csv(config.paths.participants)[0]
        self.assertEqual(revised["Review"], "OK")
        self.assertEqual(revised["Notes"], "")
        with fitz.open(config.paths.pdf_output) as doc:
            self.assertIn("FSEI", doc[0].get_text())

    def test_approved_blank_affiliation_is_not_printed(self):
        config = self.settings
        prepare(config)
        review = read_csv(config.paths.affiliation_review)
        review[0]["Approved"] = "YES"
        save_csv(config.paths.affiliation_review, review, AFFILIATION_COLUMNS)
        apply_approved(config)

        people = read_csv(config.paths.participants)
        self.assertEqual(people[2]["Institution"], "")
        self.assertEqual(people[2]["Review"], "NEED REVIEW")
        self.assertEqual(people[2]["Notes"], NO_AFFILIATION)
        generate_pdf(config)
        with fitz.open(config.paths.pdf_output) as doc:
            self.assertNotIn("Unknown University of Advanced Physical Research", doc[0].get_text())

    def test_apply_clears_only_the_resolved_affiliation_review(self):
        config = self.settings
        source = read_csv(config.paths.registrations)
        source[2]["First Name"] = ""
        save_csv(config.paths.registrations, source, tuple(source[0]))
        prepare(config)

        people = read_csv(config.paths.participants)
        self.assertIn("Unknown affiliation", people[2]["Notes"])
        self.assertIn("Missing first name", people[2]["Notes"])
        people[2]["Notes"] += " | Manual name concern"
        people[0]["Review"] = "NEED REVIEW"
        people[0]["Notes"] = "Manual spelling concern"
        save_csv(config.paths.participants, people)

        review = read_csv(config.paths.affiliation_review)
        review[0]["Suggested"] = "UAPR"
        review[0]["Approved"] = "YES"
        save_csv(config.paths.affiliation_review, review, AFFILIATION_COLUMNS)
        apply_approved(config)

        people = read_csv(config.paths.participants)
        self.assertEqual(people[2]["Institution"], "UAPR")
        self.assertEqual(people[2]["Review"], "NEED REVIEW")
        self.assertIn("Missing first name", people[2]["Notes"])
        self.assertIn("Manual name concern", people[2]["Notes"])
        self.assertNotIn("Unknown affiliation", people[2]["Notes"])
        self.assertEqual(people[0]["Review"], "NEED REVIEW")
        self.assertEqual(people[0]["Notes"], "Manual spelling concern")

    def test_given_name_wrap_and_type_filtered_pdf(self):
        config = self.settings
        font = fitz.Font(fontfile=str(find_font(config.badge.font_path)))
        wrapped = name_lines("Alfa Beta Gama Epsilon", font, config.typography.first_name)
        self.assertEqual(wrapped, ["Alfa Beta", "Gama Epsilon"])

        prepare(config)
        people = read_csv(config.paths.participants)
        people[1]["Type"] = "ORGANIZER"
        people[1]["First Name"] = "Alfa Beta Gama Epsilon"
        people[1]["Last Name"] = "Delta"
        save_csv(config.paths.participants, people)
        organizer_pdf = replace(config, paths=replace(config.paths, pdf_output=config.paths.root / "organizers.pdf"))
        generate_pdf(organizer_pdf, badge_type="ORGANIZER")
        with fitz.open(organizer_pdf.paths.pdf_output) as doc:
            self.assertEqual(len(doc), 1)
            text = doc[0].get_text().replace("\u00a0", " ")
            self.assertIn("Alfa Beta", text)
            self.assertIn("Gama Epsilon", text)
            self.assertIn("Delta", text)
            self.assertNotIn("Demo", text)

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

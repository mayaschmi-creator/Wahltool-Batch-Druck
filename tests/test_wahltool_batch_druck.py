import io
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from wahltool_batch_druck import merge_documents, sort_key


def make_pdf(page_count):
    stream = io.BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    writer.write(stream)
    writer.close()
    return stream.getvalue()


class SortingTests(unittest.TestCase):
    def test_natural_class_and_name_order(self):
        entries = [
            {"group": "12b", "last": "Z", "first": "A"},
            {"group": "9a", "last": "B", "first": "A"},
            {"group": "12b", "last": "A", "first": "B"},
            {"group": "12b", "last": "A", "first": "A"},
        ]
        result = sorted(entries, key=sort_key)
        self.assertEqual(
            [(e["group"], e["last"], e["first"]) for e in result],
            [("9a", "B", "A"), ("12b", "A", "A"),
             ("12b", "A", "B"), ("12b", "Z", "A")],
        )


class MergeTests(unittest.TestCase):
    def test_keeps_all_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "collection.pdf"
            count = merge_documents([make_pdf(1), make_pdf(2)], str(path))
            self.assertEqual(count, 3)
            self.assertEqual(len(PdfReader(path).pages), 3)

    def test_invalid_pdf_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "collection.pdf"
            original = make_pdf(1)
            path.write_bytes(original)
            with self.assertRaises(Exception):
                merge_documents([make_pdf(1), b"Not a PDF"], str(path))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ["collection.pdf"])

    def test_empty_selection_creates_no_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "collection.pdf"
            with self.assertRaises(ValueError):
                merge_documents([], str(path))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()

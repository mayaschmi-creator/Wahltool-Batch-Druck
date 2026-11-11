import unittest

from wahltool_batch_druck import extract_pages, extract_pdf_targets


class ExtractPagesTests(unittest.TestCase):
    def test_extracts_unique_titled_subpages_on_the_main_path(self):
        base_url = "https://start.schulportal.hessen.de/oberstufenwahl.php"
        anchors = [
            {"href": "?a=auswertung_pupil&w=34", "text": "  Auswertung\n Q1 "},
            {"href": "?a=auswertung_pupil&w=34", "text": "Duplikat"},
            {"href": "?a=auswertung_pupil&w=35", "text": "   ", "title": "Auswertung Q2"},
            {"href": "/anderes.php?a=1", "text": "Andere Seite"},
            {"href": "https://example.org/oberstufenwahl.php?a=1", "text": "Extern"},
            {"href": "?a=leer", "text": ""},
        ]

        self.assertEqual(
            extract_pages(base_url, anchors),
            [
                {
                    "title": "Auswertung Q1",
                    "url": base_url + "?a=auswertung_pupil&w=34",
                },
                {
                    "title": "Auswertung Q2",
                    "url": base_url + "?a=auswertung_pupil&w=35",
                },
            ],
        )


class ExtractPdfTargetsTests(unittest.TestCase):
    def test_keeps_same_origin_pdfs_and_embedded_documents(self):
        page_url = "https://start.schulportal.hessen.de/oberstufenwahl.php?a=auswertung"
        candidates = [
            {"href": "/dokumente/wahl.PDF", "kind": "a"},
            {"href": "https://example.org/privat.pdf", "kind": "a"},
            {"href": "/viewer?id=7", "kind": "iframe"},
            {"href": "/not-a-pdf", "kind": "a"},
            {"href": "/viewer?id=7", "kind": "iframe"},
        ]

        self.assertEqual(
            extract_pdf_targets(page_url, candidates),
            [
                "https://start.schulportal.hessen.de/dokumente/wahl.PDF",
                "https://start.schulportal.hessen.de/viewer?id=7",
            ],
        )


if __name__ == "__main__":
    unittest.main()
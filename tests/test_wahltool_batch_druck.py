import io
import os
import queue
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, ArrayObject, NumberObject
from wahltool_batch_druck import sort_key, merge_documents, optimize_document, Worker, load_preferences, save_preferences


def document(pages=1, crowded=False):
    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(595.28, 841.89)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        commands = f'BT /F1 12 Tf 45 780 Td (Page {index+1}) Tj ET\n'
        if crowded:
            commands += 'BT /F1 12 Tf 45 45 Td (Last line) Tj ET\n'
        stream.set_data(commands.encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO(); writer.write(output)
    return output.getvalue()


class PdfTests(unittest.TestCase):
    def test_natural_sort(self):
        entries = [dict(group=g, last=l, first=f) for g,l,f in [('12b','A','A'),('9a','B','A'),('9a','A','B'),('9a','A','A')]]
        self.assertEqual([(e['group'],e['last'],e['first']) for e in sorted(entries,key=sort_key)], [('9a','A','A'),('9a','A','B'),('9a','B','A'),('12b','A','A')])

    def test_merge_keeps_all_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'result.pdf'
            self.assertEqual(merge_documents([document(),document(2)],path),3)
            self.assertEqual(len(PdfReader(path).pages),3)

    def test_invalid_input_preserves_target(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'result.pdf'; path.write_bytes(b'previous')
            with self.assertRaises(Exception): merge_documents([document(),b'invalid'],path)
            self.assertEqual(path.read_bytes(),b'previous')
            self.assertEqual(list(Path(folder).iterdir()),[path])

    def test_empty_collection_preserves_target(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'result.pdf';path.write_bytes(b'previous')
            with self.assertRaises(ValueError):merge_documents([],path)
            self.assertEqual(path.read_bytes(),b'previous')

    def test_single_unchanged(self):
        data=document();self.assertEqual(optimize_document(data)[0],data)

    def test_three_pages_unchanged(self):
        data=document(3);self.assertEqual(optimize_document(data)[0],data)

    def test_two_pages_fit_and_keep_text(self):
        data=document(2);result,note=optimize_document(data)
        self.assertEqual(len(PdfReader(io.BytesIO(result)).pages),1)
        text=PdfReader(io.BytesIO(result)).pages[0].extract_text()
        self.assertIn('Page 1',text);self.assertIn('Page 2',text)
        self.assertIn('optimiert',note)

    def test_too_much_content_unchanged(self):
        data=document(2,True);result,note=optimize_document(data)
        self.assertEqual(result,data);self.assertIn('unverändert',note)

    def test_rotated_unchanged(self):
        reader=PdfReader(io.BytesIO(document(2)));reader.pages[0].rotate(90)
        writer=PdfWriter();writer.append(reader);buffer=io.BytesIO();writer.write(buffer)
        data=buffer.getvalue();self.assertEqual(optimize_document(data)[0],data)

    def test_annotation_unchanged(self):
        reader=PdfReader(io.BytesIO(document(2)))
        reader.pages[0][NameObject('/Annots')]=ArrayObject([DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Text'),NameObject('/Rect'):ArrayObject([NumberObject(0)]*4)})])
        writer=PdfWriter();writer.append(reader);buffer=io.BytesIO();writer.write(buffer)
        data=buffer.getvalue();self.assertEqual(optimize_document(data)[0],data)


class SettingsTests(unittest.TestCase):
    def test_settings_stay_in_local_folder(self):
        with tempfile.TemporaryDirectory() as folder, patch('wahltool_batch_druck.local_data_dir',return_value=Path(folder)):
            self.assertFalse(load_preferences())
            save_preferences(True);self.assertTrue(load_preferences())
            save_preferences(False);self.assertFalse(load_preferences())
            (Path(folder)/'settings.json').write_text('broken')
            self.assertFalse(load_preferences())


class BrowserTests(unittest.TestCase):
    def test_closed_browser_is_friendly_and_stops(self):
        self.check_closed(False)

    def test_persistent_uses_separate_profile(self):
        self.check_closed(True)

    def check_closed(self, remember):
        api=types.ModuleType('playwright.sync_api')
        manager=MagicMock();playwright=manager.__enter__.return_value
        context=MagicMock();page=MagicMock();page.is_closed.return_value=True
        context.pages=[page];context.new_page.return_value=page
        playwright.chromium.launch.return_value.new_context.return_value=context
        playwright.chromium.launch_persistent_context.return_value=context
        api.sync_playwright=lambda:manager;api.Error=Exception
        events=queue.Queue()
        with tempfile.TemporaryDirectory() as folder, patch.dict('sys.modules',{'playwright':types.ModuleType('playwright'),'playwright.sync_api':api}), patch('wahltool_batch_druck.local_data_dir',return_value=Path(folder)):
            Worker(events,remember).run()
            if remember:
                self.assertEqual(playwright.chromium.launch_persistent_context.call_args.args[0],str(Path(folder)/'edge-profile'))
        names=[]
        while not events.empty():names.append(events.get()[0])
        self.assertEqual(names,['ready','browser_closed','stopped'])


if __name__=='__main__':unittest.main()

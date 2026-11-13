import io
import os
import queue
import re
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit

DEFAULT_URL = "https://start.schulportal.hessen.de/oberstufenwahl.php"


def sort_key(entry):
    def natural(text):
        return tuple((0, int(p)) if p.isdigit() else (1, p.casefold())
                     for p in re.split(r"(\d+)", text))
    return (natural(entry["group"]), natural(entry["last"]), natural(entry["first"]))


def merge_documents(documents, destination):
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    readers = []
    temporary = None
    try:
        for data in documents:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("Ein Dokument ist passwortgeschützt.")
            if not len(reader.pages):
                raise ValueError("Ein Dokument enthält keine Seiten.")
            readers.append(reader)
            writer.append(reader, import_outline=False)
        if not readers:
            raise ValueError("Keine Dokumente vorhanden.")
        count = len(writer.pages)
        folder = os.path.dirname(os.path.abspath(destination))
        with tempfile.NamedTemporaryFile(dir=folder, suffix=".tmp", delete=False) as f:
            temporary = f.name
            writer.write(f)
        os.replace(temporary, destination)
        temporary = None
        return count
    finally:
        writer.close()
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def extract_election_title(heading):
    import unicodedata
    heading = unicodedata.normalize("NFC", str(heading or ""))
    heading = re.sub(r"\s+", " ", heading).strip()
    match = re.fullmatch(r'Teilnehmende von\s+["„“«](.+?)["“”»]', heading)
    return match.group(1).strip() if match else ""


def suggested_pdf_filename(heading):
    title = extract_election_title(heading)
    if not title:
        return "Kurswahl_Sammel.pdf"
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "-", title)
    title = re.sub(r"\s*-\s*", "-", title)
    title = re.sub(r"-+", "-", title)
    title = re.sub(r"\s+", " ", title).strip(" .-")
    title = title[:140].rstrip(" .-")
    return title + "_Sammel.pdf" if title else "Kurswahl_Sammel.pdf"


SCAN_SCRIPT = """() => ({
    heading: (() => {
        const headings = document.querySelectorAll('#content h1[data-id]');
        return headings.length === 1 ? headings[0].textContent : '';
    })(),
    url: location.href,
    paginated: Array.from(document.querySelectorAll('table[id^="vtableEx"]')).some(t => {
        if (!window.jQuery || !jQuery.fn.bootstrapTable) return false;
        const opts = jQuery(t).bootstrapTable('getOptions');
        return opts && opts.pagination && String(opts.pageSize).toLowerCase() !== 'all';
    }),
    entries: Array.from(document.querySelectorAll('table[id^="vtableEx"] tbody tr'))
      .flatMap(row => {
        const cells = row.querySelectorAll('td');
        const a = row.querySelector('a[id^="linkFile"][href]');
        if (!a || cells.length < 3) return [];
        const u = new URL(a.href, location.href);
        if (u.origin !== location.origin || u.pathname !== location.pathname ||
            u.searchParams.get('b') !== 'print') return [];
        const clean = c => c.textContent.replace(/\\s+/g, ' ').trim();
        return [{last: clean(cells[0]), first: clean(cells[1]),
                 group: clean(cells[2]), url: u.href}];
      })
})"""



def local_data_dir():
    from pathlib import Path
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / "WahltoolBatchDruck"


def load_preferences():
    import json
    try:
        return bool(json.loads((local_data_dir() / "settings.json").read_text(encoding="utf-8")).get("remember", False))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def save_preferences(remember):
    import json
    folder = local_data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "settings.json").write_text(json.dumps({"remember": bool(remember)}), encoding="utf-8")


class BrowserClosed(Exception):
    pass


def optimize_document(data):
    """Conservative two-page layout; return original bytes on any uncertainty."""
    import copy
    import math
    import pdfplumber
    from pypdf import PdfReader, PdfWriter, Transformation
    from pypdf.generic import RectangleObject
    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) == 1:
        return data, "einseitig – unverändert"
    if len(reader.pages) != 2:
        return data, "nicht zweiseitig – unverändert"
    try:
        bounds = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for i, page in enumerate(pdf.pages):
                source = reader.pages[i]
                if source.rotation or source.get("/Annots") or source.get("/UserUnit", 1) != 1:
                    raise ValueError("Drehung, Formular oder Anmerkungen")
                if any(abs(float(v)) > 0.1 for v in source.mediabox.lower_left):
                    raise ValueError("abweichender Seitenursprung")
                if abs(page.width - 595.28) > 2 or abs(page.height - 841.89) > 2:
                    raise ValueError("kein A4-Hochformat")
                if list(source.cropbox) != list(source.mediabox):
                    raise ValueError("bereits beschnittene Seite")
                if not page.chars or page.images:
                    raise ValueError("Bildinhalt oder kein prüfbarer Text")
                objects = [o for group in page.objects.values() for o in group]
                if any(o.get("object_type") not in {"char", "line", "rect", "curve"} for o in objects):
                    raise ValueError("unbekannter Inhalt")
                coords = [(float(o["x0"]), float(o["top"]), float(o["x1"]), float(o["bottom"])) for o in objects]
                if not all(math.isfinite(v) for box in coords for v in box):
                    raise ValueError("ungültige Position")
                if any(x0 < 0 or y0 < 0 or x1 > page.width or y1 > page.height for x0,y0,x1,y1 in coords):
                    raise ValueError("Inhalt außerhalb der Seite")
                top = max(0, min(b[1] for b in coords) - 3)
                bottom = min(page.height, max(b[3] for b in coords) + 3)
                bounds.append((top, bottom))
        w, h, margin, gap = 595.28, 841.89, 28, 24
        needed = sum(b-t for t,b in bounds) + gap
        scale = min(0.95, math.floor((h-2*margin)/needed*100)/100)
        if scale < 0.85:
            return data, "mehr als 15 % Verkleinerung nötig – unverändert"
        writer = PdfWriter()
        target = writer.add_blank_page(w, h)
        y = margin
        for source, (top, bottom) in zip(reader.pages, bounds):
            p = copy.deepcopy(source)
            ph = float(p.mediabox.height)
            p.cropbox = RectangleObject((0, ph-bottom, float(p.mediabox.width), ph-top))
            target.merge_transformed_page(p, Transformation().scale(scale).translate(
                (w-float(p.mediabox.width)*scale)/2, h-y-scale*(ph-top)))
            y += (bottom-top+gap)*scale
        result = io.BytesIO()
        writer.write(result)
        payload = result.getvalue()
        check = PdfReader(io.BytesIO(payload))
        clean = lambda text: re.sub(r"\s+", "", text)
        original = clean("".join(p.extract_text() or "" for p in reader.pages))
        if not original or clean(check.pages[0].extract_text() or "") != original:
            raise ValueError("Textvergleich fehlgeschlagen")
        return payload, f"optimiert auf {int(round(scale*100))} %"
    except Exception as error:
        return data, f"Layout nicht sicher optimierbar ({type(error).__name__}) – unverändert"


class Worker(threading.Thread):
    def __init__(self, events, remember=False):
        super().__init__(daemon=True)
        self.events = events
        self.commands = queue.Queue()
        self.remember = remember

    def run(self):
        try:
            from playwright.sync_api import sync_playwright, Error
            with sync_playwright() as p:
                if self.remember:
                    profile = local_data_dir() / "edge-profile"
                    profile.mkdir(parents=True, exist_ok=True)
                    context = p.chromium.launch_persistent_context(
                        str(profile), channel="msedge", headless=False, accept_downloads=True,
                        chromium_sandbox=True)
                else:
                    browser = p.chromium.launch(channel="msedge", headless=False, chromium_sandbox=True)
                    context = browser.new_context(accept_downloads=True)
                self.context = context
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(DEFAULT_URL, wait_until="domcontentloaded")
                self.events.put(("ready", None))
                while True:
                    if page.is_closed():
                        raise BrowserClosed()
                    page.wait_for_timeout(100)
                    try:
                        action, payload = self.commands.get_nowait()
                    except queue.Empty:
                        continue
                    if action == "close":
                        context.close()
                        return
                    try:
                        if action == "scan":
                            for attempt in range(3):
                                try:
                                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                                    snapshot = page.evaluate(SCAN_SCRIPT)
                                    break
                                except Error as error:
                                    if "Execution context was destroyed" not in str(error) or attempt == 2:
                                        raise
                                    page.wait_for_timeout(300)
                            if snapshot["paginated"]:
                                raise ValueError("Bitte im Portal die Anzahl der Tabellenzeilen auf 'Alle / All' stellen und erneut einlesen.")
                            entries, seen = [], set()
                            for entry in snapshot["entries"]:
                                if entry["url"] not in seen:
                                    entries.append(entry)
                                    seen.add(entry["url"])
                            entries.sort(key=sort_key)
                            self.events.put(("entries", (entries, snapshot.get("heading", ""))))
                        elif action == "collect":
                            entries, destination, optimize = payload
                            documents = []
                            report = []
                            for index, entry in enumerate(entries, 1):
                                if page.is_closed():
                                    raise BrowserClosed()
                                self.events.put(("progress", (index, len(entries))))
                                target = urlsplit(entry["url"])
                                source = urlsplit(page.url)
                                if (target.scheme, target.netloc) != (source.scheme, source.netloc):
                                    raise ValueError("Dokumentadresse gehört nicht zur aktuellen Portal-Domain.")
                                if parse_qs(target.query).get("b") != ["print"]:
                                    raise ValueError("Ungültiger Dokumentlink.")
                                response = context.request.get(
                                    entry["url"], headers={"Referer": page.url}, timeout=60000
                                )
                                try:
                                    if not response.ok:
                                        raise ValueError(f"HTTP-Fehler {response.status} bei Dokument {index}.")
                                    data = response.body()
                                    if b"%PDF-" not in data[:1024]:
                                        raise ValueError(
                                            f"Dokument {index} liefert keine PDF-Datei. "
                                            "Möglicherweise ist die Anmeldung abgelaufen oder der PDF-Aufruf benötigt weitere Verarbeitung."
                                        )
                                    from pypdf import PdfReader
                                    check = PdfReader(io.BytesIO(data))
                                    if check.is_encrypted and not check.decrypt(""):
                                        raise ValueError(f"Dokument {index} ist passwortgeschützt.")
                                    if not len(check.pages):
                                        raise ValueError(f"Dokument {index} ist leer.")
                                    if optimize:
                                        data, note = optimize_document(data)
                                        report.append(f"{entry['group']} | {entry['last']}, {entry['first']}: {note}")
                                    documents.append(data)
                                finally:
                                    response.dispose()
                            if page.is_closed():
                                raise BrowserClosed()
                            count = merge_documents(documents, destination)
                            self.events.put(("done", (destination, len(entries), count, report)))
                    except Exception as error:
                        if isinstance(error, BrowserClosed) or page.is_closed():
                            raise BrowserClosed() from error
                        self.events.put(("operation_error", str(error)))
        except Exception as error:
            if isinstance(error, BrowserClosed) or "Target page, context or browser has been closed" in str(error):
                self.events.put(("browser_closed", None))
            else:
                self.events.put(("fatal", str(error)))
        finally:
            try:
                self.context.close()
            except Exception:
                pass
            self.events.put(("stopped", None))


class App:
    def __init__(self, root):
        global tk, filedialog, messagebox, ttk
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        self.root = root
        root.title("Wahltool – Sammel-PDF | Dateiname-Update 2 | Sandbox aktiv")
        root.geometry("960x740")
        self.events = queue.Queue()
        self.worker = None
        self.entries = []
        self.checked = set()
        self.busy = False
        self.closing = False
        self.last_pdf_path = None
        self.suggested_filename = "Kurswahl_Sammel.pdf"
        self.election_info = tk.StringVar(value="Wahlname wird beim Einlesen ermittelt.")
        self.remember_var = tk.BooleanVar(value=load_preferences())
        self.optimize_var = tk.BooleanVar(value=False)
        self.all_var = tk.BooleanVar(value=False)
        frame = ttk.Frame(root, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="1. Portal öffnen und anmelden.  2. Abgaben der gewünschten Wahl öffnen.\n"
                  "3. Tabellenfilter leeren und alle Zeilen anzeigen.  4. Teilnehmende einlesen.").pack(anchor="w")
        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=12)
        self.open_btn = ttk.Button(controls, text="Portal öffnen", command=self.open_portal)
        self.open_btn.pack(side="left")
        self.scan_btn = ttk.Button(controls, text="Teilnehmende einlesen", command=self.scan, state="disabled")
        self.scan_btn.pack(side="left", padx=8)
        self.all_btn = ttk.Checkbutton(controls, text="Alle auswählen", variable=self.all_var, command=self.toggle_all, state="disabled")
        self.all_btn.pack(side="left", padx=8)
        options = ttk.Frame(frame)
        options.pack(fill="x", pady=4)
        self.remember_btn = ttk.Checkbutton(options, text="Schule / Sitzung auf diesem Rechner merken", variable=self.remember_var)
        self.remember_btn.pack(side="left")
        self.forget_btn = ttk.Button(options, text="Gespeicherte Browserdaten löschen", command=self.forget_profile)
        self.forget_btn.pack(side="left", padx=8)
        ttk.Label(frame, text="Nur auf eigenem Windows-Konto verwenden. Anmeldung kann trotzdem ablaufen.").pack(anchor="w")
        self.optimize_btn = ttk.Checkbutton(frame, text="Zweiseitige Abgaben nach Möglichkeit auf eine A4-Seite verdichten (mindestens 85 %)", variable=self.optimize_var)
        self.optimize_btn.pack(anchor="w", pady=(6, 2))
        ttk.Label(frame, text="Die Ein-Seiten-Optimierung kann die Verarbeitung merklich verlangsamen – bei vielen Abgaben bleibt Zeit für einen Kaffee.", wraplength=900).pack(anchor="w", pady=(0, 6))
        ttk.Label(frame, text="Reihenfolge: Klasse/Kommentar → Nachname → Vorname (natürliche Sortierung).").pack(anchor="w")
        ttk.Label(frame, textvariable=self.election_info, wraplength=900).pack(anchor="w")
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True, pady=8)
        self.table = ttk.Treeview(table_frame, columns=("check", "last", "first", "group"), show="headings", selectmode="none", height=8)
        for col, title, width in [("check", "Auswahl", 70), ("last", "Nachname", 220), ("first", "Vorname", 180), ("group", "Klasse/Kommentar", 300)]:
            self.table.heading(col, text=title)
            self.table.column(col, width=width, anchor="w")
        self.table.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scroll.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scroll.set)
        self.table.bind("<Button-1>", self.toggle_row)
        result_controls = ttk.Frame(frame)
        result_controls.pack(fill="x", pady=8)
        self.save_btn = ttk.Button(result_controls, text="Sammel-PDF erstellen …", command=self.collect, state="disabled")
        self.save_btn.pack(side="left")
        self.pdf_open_btn = ttk.Button(result_controls, text="Sammel-PDF öffnen", command=self.open_pdf, state="disabled")
        self.pdf_open_btn.pack(side="left", padx=8)
        self.status = tk.StringVar(value="Bereit. Es wird nichts automatisch gedruckt.")
        ttk.Label(frame, textvariable=self.status, wraplength=850).pack(anchor="w")
        report_frame = ttk.LabelFrame(frame, text="Ergebnis der letzten Sammlung", padding=6)
        report_frame.pack(fill="x", pady=(8, 0))
        from tkinter.scrolledtext import ScrolledText
        self.report_text = ScrolledText(report_frame, height=5, wrap="word", font="TkDefaultFont")
        self.report_text.pack(fill="x")
        self.show_report(["Noch keine Sammel-PDF erstellt."])
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def update_controls(self):
        alive = bool(self.worker and self.worker.is_alive())
        self.open_btn.configure(state="disabled" if alive or self.busy or self.closing else "normal")
        self.remember_btn.configure(state="disabled" if alive or self.closing else "normal")
        self.forget_btn.configure(state="disabled" if alive or self.closing else "normal")
        self.optimize_btn.configure(state="disabled" if self.busy or self.closing else "normal")
        self.scan_btn.configure(state="normal" if alive and not self.busy and not self.closing else "disabled")
        self.all_btn.configure(state="normal" if self.entries and not self.busy and not self.closing else "disabled")
        self.save_btn.configure(state="normal" if alive and self.checked and not self.busy and not self.closing else "disabled")
        self.pdf_open_btn.configure(state="normal" if self.last_pdf_path and not self.busy and not self.closing else "disabled")
        self.all_var.set(bool(self.entries) and len(self.checked) == len(self.entries))

    def clear_entries(self):
        self.suggested_filename = "Kurswahl_Sammel.pdf"
        self.election_info.set("Wahlname wird beim Einlesen ermittelt.")
        self.entries = []
        self.checked.clear()
        for row in self.table.get_children():
            self.table.delete(row)

    def forget_profile(self):
        import shutil
        if self.worker is not None:
            return
        if not messagebox.askyesno("Browserdaten löschen", "Gespeicherte Schule und Portal-Sitzung dieses Wahltools auf diesem Rechner löschen? Das normale Edge-Profil bleibt unverändert."):
            return
        try:
            profile = local_data_dir() / "edge-profile"
            if profile.exists():
                shutil.rmtree(profile)
            self.remember_var.set(False)
            save_preferences(False)
            self.status.set("Lokale Browserdaten des Wahltools gelöscht.")
        except Exception as error:
            messagebox.showerror("Browserdaten löschen", str(error))

    def open_portal(self):
        if self.worker is not None:
            return
        try:
            save_preferences(self.remember_var.get())
        except OSError as error:
            messagebox.showerror("Einstellungen speichern", str(error))
            return
        self.clear_entries()
        self.busy = True
        self.worker = Worker(self.events, self.remember_var.get())
        self.worker.start()
        self.status.set("Edge wird geöffnet …")
        self.update_controls()

    def scan(self):
        self.busy = True
        self.status.set("Lese PDF-Aktionen aus der aktuellen Teilnehmendentabelle …")
        self.worker.commands.put(("scan", None))
        self.update_controls()

    def toggle_row(self, event):
        if self.busy or self.table.identify_region(event.x, event.y) != "cell":
            return
        row = self.table.identify_row(event.y)
        if row:
            index = int(row)
            if index in self.checked:
                self.checked.remove(index)
            else:
                self.checked.add(index)
            self.refresh_selection()

    def toggle_all(self):
        self.checked = set(range(len(self.entries))) if self.all_var.get() else set()
        self.refresh_selection()

    def refresh_selection(self):
        for i in range(len(self.entries)):
            self.table.set(str(i), "check", "☑" if i in self.checked else "☐")
        self.status.set(f"{len(self.checked)} von {len(self.entries)} Personen ausgewählt.")
        self.update_controls()

    def collect(self):
        if not self.checked or self.busy:
            return
        path = filedialog.asksaveasfilename(title="Sammel-PDF speichern", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")], initialfile=self.suggested_filename)
        if not path:
            return
        selected = [e.copy() for i, e in enumerate(self.entries) if i in self.checked]
        selected.sort(key=sort_key)
        self.busy = True
        self.last_pdf_path = None
        self.show_report(["Sammlung läuft. Das Ergebnis wird nach erfolgreichem Abschluss hier angezeigt."])
        self.worker.commands.put(("collect", (selected, path, self.optimize_var.get())))
        self.status.set("PDF-Dokumente werden abgerufen. Bitte nicht im Portal navigieren.")
        self.update_controls()

    def poll(self):
        try:
            while True:
                event, data = self.events.get_nowait()
                if event == "ready":
                    self.busy = False
                    self.status.set("Bitte anmelden, Abgabenübersicht öffnen und Teilnehmende einlesen.")
                elif event == "entries":
                    self.busy = False
                    data, heading = data
                    title = extract_election_title(heading)
                    self.suggested_filename = suggested_pdf_filename(heading)
                    if title and self.suggested_filename != "Kurswahl_Sammel.pdf":
                        self.election_info.set(f"Erkannte Wahl: {title} | Dateiname: {self.suggested_filename}")
                    else:
                        self.election_info.set("Kein eindeutiger Wahlname erkannt. Dateiname: Kurswahl_Sammel.pdf (kann beim Speichern geändert werden).")
                    self.entries = data
                    self.checked.clear()
                    for row in self.table.get_children():
                        self.table.delete(row)
                    for i, e in enumerate(data):
                        self.table.insert("", "end", iid=str(i), values=("☐", e["last"], e["first"], e["group"]))
                    self.status.set(f"{len(data)} PDF-Einträge gefunden. Bitte auswählen." if data else "Keine PDF-Aktionen gefunden. Ist die Teilnehmenden-/Abgabenübersicht geöffnet?")
                elif event == "progress":
                    self.status.set(f"Rufe Dokument {data[0]} von {data[1]} ab …")
                elif event == "done":
                    self.busy = False
                    path, people, pages, report = data
                    self.last_pdf_path = path
                    summary = f"Fertig: {people} Dokumente, {pages} Seiten. Sammel-PDF gespeichert."
                    self.show_report([summary, ""] + (report or ["Ein-Seiten-Optimierung nicht aktiviert. Alle Dokumente unverändert zusammengeführt."]))
                    self.status.set(summary)
                elif event == "browser_closed":
                    if self.busy:
                        self.show_report(["Browser wurde geschlossen. Keine neue Sammel-PDF fertiggestellt."])
                    self.busy = False
                    self.clear_entries()
                    self.status.set("Browser wurde geschlossen. Bitte Portal erneut öffnen und Teilnehmende neu einlesen. Keine unvollständige Sammlung gespeichert.")
                elif event == "stopped":
                    self.worker = None
                    self.busy = False
                    if self.closing:
                        self.root.destroy()
                        return
                elif event in ("operation_error", "fatal"):
                    self.busy = False
                    if event == "fatal":
                        self.clear_entries()
                    self.status.set("Vorgang fehlgeschlagen. Keine neue Sammel-PDF fertiggestellt.")
                    self.show_report(["Vorgang fehlgeschlagen. Keine neue Sammel-PDF fertiggestellt.", str(data)])
                    messagebox.showerror("Wahltool", data + "\n\nBei einem PDF-Abruffehler bleibt eine vorhandene Zieldatei unverändert.")
                self.update_controls()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def show_report(self, report):
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", "\n".join(report))
        self.report_text.configure(state="disabled")
        self.report_text.yview_moveto(0)

    def open_pdf(self):
        if not self.last_pdf_path or self.busy or self.closing:
            return
        try:
            os.startfile(self.last_pdf_path)
        except Exception as error:
            messagebox.showerror("PDF öffnen", str(error))

    def close(self):
        if self.closing:
            return
        if self.busy and not messagebox.askyesno("Beenden", "Ein Vorgang läuft. Nach dessen Abschluss Browser und Wahltool schließen?"):
            return
        if self.worker is not None:
            self.closing = True
            self.worker.commands.put(("close", None))
            self.status.set("Warte auf Abschluss des laufenden Vorgangs und schließe den Browser …")
            self.update_controls()
        else:
            self.root.destroy()


if __name__ == "__main__":
    import tkinter as tk
    root = tk.Tk()
    App(root)
    root.mainloop()

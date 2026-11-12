import io
import os
import queue
import re
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
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


SCAN_SCRIPT = """() => ({
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


class Worker(threading.Thread):
    def __init__(self, events):
        super().__init__(daemon=True)
        self.events = events
        self.commands = queue.Queue()

    def run(self):
        try:
            from playwright.sync_api import sync_playwright, Error
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="msedge", headless=False)
                context = browser.new_context(accept_downloads=True)
                page = context.new_page()
                page.goto(DEFAULT_URL, wait_until="domcontentloaded")
                self.events.put(("ready", None))
                while True:
                    page.wait_for_timeout(100)
                    try:
                        action, payload = self.commands.get_nowait()
                    except queue.Empty:
                        continue
                    if action == "close":
                        browser.close()
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
                            self.events.put(("entries", entries))
                        elif action == "collect":
                            entries, destination = payload
                            documents = []
                            for index, entry in enumerate(entries, 1):
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
                                    documents.append(data)
                                finally:
                                    response.dispose()
                            count = merge_documents(documents, destination)
                            self.events.put(("done", (destination, len(entries), count)))
                    except Exception as error:
                        self.events.put(("operation_error", str(error)))
        except Exception as error:
            self.events.put(("fatal", str(error)))


class App:
    def __init__(self, root):
        self.root = root
        root.title("Wahltool – Sammel-PDF")
        root.geometry("900x610")
        self.events = queue.Queue()
        self.worker = None
        self.entries = []
        self.checked = set()
        self.busy = False
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
        ttk.Label(frame, text="Reihenfolge: Klasse/Kommentar → Nachname → Vorname (natürliche Sortierung).").pack(anchor="w")
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True, pady=8)
        self.table = ttk.Treeview(table_frame, columns=("check", "last", "first", "group"), show="headings", selectmode="none")
        for col, title, width in [("check", "Auswahl", 70), ("last", "Nachname", 220), ("first", "Vorname", 180), ("group", "Klasse/Kommentar", 300)]:
            self.table.heading(col, text=title)
            self.table.column(col, width=width, anchor="w")
        self.table.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scroll.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=scroll.set)
        self.table.bind("<Button-1>", self.toggle_row)
        self.save_btn = ttk.Button(frame, text="Sammel-PDF erstellen …", command=self.collect, state="disabled")
        self.save_btn.pack(anchor="w", pady=8)
        self.status = tk.StringVar(value="Bereit. Es wird nichts automatisch gedruckt.")
        ttk.Label(frame, textvariable=self.status, wraplength=850).pack(anchor="w")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def update_controls(self):
        alive = bool(self.worker and self.worker.is_alive())
        self.open_btn.configure(state="disabled" if alive else "normal")
        self.scan_btn.configure(state="normal" if alive and not self.busy else "disabled")
        self.all_btn.configure(state="normal" if self.entries and not self.busy else "disabled")
        self.save_btn.configure(state="normal" if alive and self.checked and not self.busy else "disabled")
        self.all_var.set(bool(self.entries) and len(self.checked) == len(self.entries))

    def open_portal(self):
        self.busy = True
        self.worker = Worker(self.events)
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
        path = filedialog.asksaveasfilename(title="Sammel-PDF speichern", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")], initialfile="Kurswahl_Sammel.pdf")
        if not path:
            return
        selected = [e.copy() for i, e in enumerate(self.entries) if i in self.checked]
        selected.sort(key=sort_key)
        self.busy = True
        self.worker.commands.put(("collect", (selected, path)))
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
                    path, people, pages = data
                    self.status.set(f"Fertig: {people} Dokumente, {pages} Seiten. Sammel-PDF gespeichert.")
                    if messagebox.askyesno("Sammel-PDF fertig", f"{people} Dokumente mit insgesamt {pages} Seiten gespeichert.\n\nPDF jetzt zur Kontrolle öffnen?"):
                        try:
                            os.startfile(path)
                        except Exception as error:
                            messagebox.showerror("PDF öffnen", str(error))
                elif event in ("operation_error", "fatal"):
                    self.busy = False
                    if event == "fatal":
                        self.worker = None
                    self.status.set("Vorgang fehlgeschlagen. Keine neue Sammel-PDF fertiggestellt.")
                    messagebox.showerror("Wahltool", data + "\n\nBei einem PDF-Abruffehler bleibt eine vorhandene Zieldatei unverändert.")
                self.update_controls()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        if self.busy and not messagebox.askyesno("Beenden", "Ein Vorgang läuft. Wirklich beenden? Eine laufende Sammlung wird möglicherweise nicht fertiggestellt."):
            return
        if self.worker and self.worker.is_alive():
            self.worker.commands.put(("close", None))
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()

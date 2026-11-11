import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urljoin, urlsplit, urlunsplit


DEFAULT_URL = "https://start.schulportal.hessen.de/oberstufenwahl.php"


def _origin(url):
    parts = urlsplit(url)
    return parts.scheme.lower(), parts.netloc.lower()


def extract_pages(base_url, anchors):
    base = urlsplit(base_url)
    pages = []
    seen = set()
    for anchor in anchors:
        href = urljoin(base_url, anchor.get("href", ""))
        target = urlsplit(href)
        title = " ".join((anchor.get("text") or "").split())
        if not title:
            title = " ".join((anchor.get("title") or "").split())
        normalized = urlunsplit((target.scheme, target.netloc, target.path, target.query, ""))
        if not title or _origin(href) != _origin(base_url) or target.path != base.path:
            continue
        if normalized == urlunsplit((base.scheme, base.netloc, base.path, base.query, "")):
            continue
        if normalized not in seen:
            pages.append({"title": title, "url": normalized})
            seen.add(normalized)
    return pages


def extract_pdf_targets(page_url, candidates):
    targets = []
    seen = set()
    for candidate in candidates:
        href = urljoin(page_url, candidate.get("href", ""))
        parsed = urlsplit(href)
        is_pdf = parsed.path.lower().endswith(".pdf")
        is_embedded = candidate.get("kind") in {"iframe", "embed", "object"}
        if _origin(href) != _origin(page_url) or not (is_pdf or is_embedded):
            continue
        normalized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
        if normalized not in seen:
            targets.append(normalized)
            seen.add(normalized)
    return targets


class BrowserWorker(threading.Thread):
    def __init__(self, events):
        super().__init__(daemon=True)
        self.events = events
        self.commands = queue.Queue()

    def send(self, command, payload=None):
        self.commands.put((command, payload))

    def run(self):
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    channel="msedge",
                    headless=False,
                    args=["--kiosk-printing"]
                )
                context = browser.new_context()
                page = context.new_page()

                self.events.put((
                    "status",
                    "Edge geöffnet. Bitte im Portal anmelden."
                ))

                while True:
                    command, payload = self.commands.get()

                    if command == "open":
                        page.goto(
                            payload,
                            wait_until="domcontentloaded"
                        )
                        self.events.put((
                            "status",
                            "Portal geöffnet. Bitte anmelden und "
                            "die Wahlübersicht öffnen, dann Seiten suchen."
                        ))

                    elif command == "scan":
                        current_url = page.url
                        anchors = page.evaluate(
                            """() => Array.from(
                                document.querySelectorAll('a[href]')
                            ).map(a => ({
                                href: a.href,
                                text: a.innerText || '',
                                title: a.getAttribute('title') || ''
                            }))"""
                        )
                        pages = extract_pages(current_url, anchors)
                        self.events.put(("pages", pages))

                    elif command == "print":
                        self._print_pages(page, payload)

                    elif command == "close":
                        browser.close()
                        return

        except Exception as error:
            self.events.put(("error", str(error)))
    def _print_pages(self, page, selected_pages):
        total = len(selected_pages)
        for index, selected in enumerate(selected_pages, start=1):
            self.events.put(("status", f"Seite {index}/{total}: {selected['title']}"))
            response = page.goto(selected["url"], wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            content_type = ""
            if response:
                content_type = response.headers.get("content-type", "").lower()
            if "application/pdf" in content_type:
                self._print_current(page)
                continue

            candidates = page.evaluate(
                """() => Array.from(document.querySelectorAll(
                    'a[href], iframe[src], embed[src], object[data]'
                )).map(element => ({
                   href: element.href || element.src || element.data || '',
                    kind: element.tagName.toLowerCase()
                }))"""
            )
            pdfs = extract_pdf_targets(selected["url"], candidates)
            for pdf_url in pdfs:
                page.goto(pdf_url, wait_until="domcontentloaded")
                page.wait_for_timeout(500)
                self._print_current(page)
            if not pdfs:
                self._print_current(page)
        self.events.put(("status", "Druckauftrag abgeschlossen."))

    @staticmethod
    def _print_current(page):
        page.evaluate("window.print()")


class BatchPrintApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Wahltool Batch-Druck")
        self.root.geometry("720x520")
        self.events = queue.Queue()
        self.worker = None
        self.pages = []

        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Schulportal Hessen").pack(anchor="w")
        ttk.Label(frame, text="Hauptseite").pack(anchor="w", pady=(14, 4))
        self.url = DEFAULT_URL
        ttk.Label(frame, text=DEFAULT_URL).pack(anchor="w")

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=12)
        self.open_button = ttk.Button(controls, text="Portal öffnen", command=self.open_portal)
        self.open_button.pack(side="left")
        self.scan_button = ttk.Button(
            controls, text="Seiten suchen", command=self.scan_pages, state="disabled"
        )
        self.scan_button.pack(side="left", padx=8)
        self.print_button = ttk.Button(
            controls, text="Auswahl drucken", command=self.print_selected, state="disabled"
        )
        self.print_button.pack(side="left")

        ttk.Label(frame, text="Verfügbare Unterseiten").pack(anchor="w", pady=(6, 4))
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True)
        self.page_list = tk.Listbox(list_frame, selectmode="extended", exportselection=False)
        self.page_list.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.page_list.yview)
        scrollbar.pack(side="right", fill="y")
        self.page_list.configure(yscrollcommand=scrollbar.set)

        self.status = tk.StringVar(value="Bereit.")
        ttk.Label(frame, textvariable=self.status, wraplength=680).pack(anchor="w", pady=(12, 0))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.poll_events)

    def open_portal(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Portal", "Der Browser ist bereits geöffnet.")
            return
        self.worker = BrowserWorker(self.events)
        self.worker.start()
        self.worker.send("open", self.url.strip())
        self.scan_button.configure(state="normal")
        self.open_button.configure(state="disabled")
        self.status.set("Browser wird gestartet …")

    def scan_pages(self):
        if not self._browser_ready():
            return
        self.status.set("Suche Unterseiten …")
        self.worker.send("scan", self.url.strip())

    def print_selected(self):
        selected = self.page_list.curselection()
        if not selected:
            messagebox.showinfo("Batch-Druck", "Bitte mindestens eine Unterseite auswählen.")
            return
        pages = [self.pages[index] for index in selected]
        if not messagebox.askyesno(
            "Batch-Druck",
            f"{len(pages)} ausgewählte Unterseite(n) an den Standarddrucker senden?",
        ):
            return
        self.print_button.configure(state="disabled")
        self.worker.send("print", pages)

    def poll_events(self):
        while not self.events.empty():
            event, payload = self.events.get()
            if event == "status":
                self.status.set(payload)
                if payload == "Druckauftrag abgeschlossen.":
                    self.print_button.configure(state="normal")
            elif event == "pages":
                self.pages = payload
                self.page_list.delete(0, tk.END)
                for item in self.pages:
                    self.page_list.insert(tk.END, item["title"])
                self.print_button.configure(state="normal" if self.pages else "disabled")
                self.status.set(
                    f"{len(self.pages)} Unterseite(n) gefunden."
                    if self.pages
                    else "Keine Unterseiten gefunden. Bitte im Portal anmelden und erneut suchen."
                )
            elif event == "error":
                self.status.set("Fehler beim Öffnen oder Drucken.")
                self.open_button.configure(state="normal")
                self.scan_button.configure(state="disabled")
                self.print_button.configure(state="disabled")
                messagebox.showerror(
                    "Wahltool Batch-Druck",
                    "Der Browser konnte nicht gestartet oder die Aktion nicht ausgeführt werden.\n\n"
                    f"Details: {payload}\n\nBitte Microsoft Edge installieren und erneut versuchen.",
                )
        self.root.after(100, self.poll_events)

    def _browser_ready(self):
        if self.worker and self.worker.is_alive():
            return True
        messagebox.showinfo("Portal", "Bitte zuerst das Portal öffnen.")
        return False

    def close(self):
        if self.worker and self.worker.is_alive():
            self.worker.send("close")
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    BatchPrintApp(root)
    root.mainloop()

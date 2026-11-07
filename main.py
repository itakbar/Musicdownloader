import os
import threading

try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import platform

from yt_dlp import YoutubeDL

Window.softinput_mode = "below_target"


# ---------- Файлы и Android ----------

def storage_root():
    if platform == "android":
        try:
            from android.storage import primary_external_storage_path
            return primary_external_storage_path()
        except Exception:
            return "/storage/emulated/0"
    return os.path.expanduser("~")


def get_folder(mode):
    """Аудио -> Music, видео -> Movies. Если нельзя писать, то Download."""
    name = "Music" if mode == "a" else "Movies"
    root = storage_root()
    for sub in (name, "Download"):
        path = os.path.join(root, sub)
        try:
            os.makedirs(path, exist_ok=True)
            if os.access(path, os.W_OK):
                return path
        except Exception:
            continue
    return root


def scan_media(path):
    """Просит Android добавить файл в медиатеку, чтобы плеер его увидел."""
    if platform != "android":
        return
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        MediaScannerConnection = autoclass("android.media.MediaScannerConnection")
        MediaScannerConnection.scanFile(PythonActivity.mActivity, [path], None, None)
    except Exception as ex:
        print("Скан медиа не удался:", ex)


# ---------- YouTube ----------

def fmt_duration(sec):
    if not sec:
        return "?"
    sec = int(sec)
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def search(query, limit=8):
    opts = {"quiet": True, "extract_flat": True, "skip_download": True, "cachedir": False}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    results = []
    for e in info.get("entries", []):
        if not e:
            continue
        url = e.get("url") or f"https://www.youtube.com/watch?v={e['id']}"
        results.append({
            "title": e.get("title", "Без названия"),
            "channel": e.get("channel") or e.get("uploader") or "?",
            "duration": fmt_duration(e.get("duration")),
            "url": url,
        })
    return results


def download(url, mode, folder, on_progress):
    """mode: 'a' = аудио (m4a), 'v' = видео (mp4). Возвращает путь к файлу."""
    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                on_progress(d.get("downloaded_bytes", 0) * 100 / total)

    opts = {
        "outtmpl": os.path.join(folder, "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "cachedir": False,
        "progress_hooks": [hook],
        "format": "bestaudio[ext=m4a]/bestaudio" if mode == "a" else "best[ext=mp4]/best",
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        downloads = info.get("requested_downloads") or []
        path = downloads[0].get("filepath") if downloads else None
        return path or ydl.prepare_filename(info)


# ---------- Интерфейс ----------

def wrapped_label(text="", **kw):
    lbl = Label(text=text, halign="left", valign="middle", **kw)
    lbl.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)))
    return lbl


class MusicApp(App):
    def build(self):
        self.title = "Music Downloader"
        self.busy = False

        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))

        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        self.query = TextInput(hint_text="Название песни или видео",
                               multiline=False, write_tab=False)
        self.query.bind(on_text_validate=lambda *_: self.start_search())
        find_btn = Button(text="Найти", size_hint_x=None, width=dp(90))
        find_btn.bind(on_release=lambda *_: self.start_search())
        row.add_widget(self.query)
        row.add_widget(find_btn)
        root.add_widget(row)

        self.status = wrapped_label("Введи название и нажми «Найти»",
                                    size_hint_y=None, height=dp(56))
        root.add_widget(self.status)

        scroll = ScrollView()
        self.results_box = GridLayout(cols=1, spacing=dp(10), size_hint_y=None)
        self.results_box.bind(minimum_height=self.results_box.setter("height"))
        scroll.add_widget(self.results_box)
        root.add_widget(scroll)
        return root

    def on_start(self):
        if platform == "android":
            try:
                from android.permissions import request_permissions
                request_permissions([
                    "android.permission.WRITE_EXTERNAL_STORAGE",
                    "android.permission.READ_EXTERNAL_STORAGE",
                    "android.permission.READ_MEDIA_AUDIO",
                    "android.permission.READ_MEDIA_VIDEO",
                ])
            except Exception as ex:
                print("Разрешения:", ex)

    def set_status(self, text):
        Clock.schedule_once(lambda dt: setattr(self.status, "text", text))

    # --- поиск ---
    def start_search(self):
        q = self.query.text.strip()
        if not q:
            return
        self.results_box.clear_widgets()
        self.set_status("Ищу...")
        threading.Thread(target=self._search_worker, args=(q,), daemon=True).start()

    def _search_worker(self, q):
        try:
            results = search(q)
        except Exception as ex:
            self.set_status(f"Ошибка поиска: {ex}")
            return
        Clock.schedule_once(lambda dt: self.show_results(results))

    def show_results(self, results):
        self.results_box.clear_widgets()
        if not results:
            self.set_status("Ничего не найдено.")
            return
        self.set_status(f"Найдено: {len(results)}")
        for r in results:
            card = BoxLayout(orientation="vertical", size_hint_y=None,
                             height=dp(150), spacing=dp(4))
            card.add_widget(wrapped_label(r["title"], bold=True))
            card.add_widget(wrapped_label(f"{r['channel']} | {r['duration']}",
                                          size_hint_y=None, height=dp(24),
                                          font_size="13sp"))
            btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
            a_btn = Button(text="Аудио (m4a)")
            v_btn = Button(text="Видео (mp4)")
            a_btn.bind(on_release=lambda _b, u=r["url"]: self.start_download(u, "a"))
            v_btn.bind(on_release=lambda _b, u=r["url"]: self.start_download(u, "v"))
            btns.add_widget(a_btn)
            btns.add_widget(v_btn)
            card.add_widget(btns)
            self.results_box.add_widget(card)

    # --- скачивание ---
    def start_download(self, url, mode):
        if self.busy:
            self.set_status("Подожди, идёт другая загрузка...")
            return
        self.busy = True
        self.set_status("Начинаю скачивание...")
        threading.Thread(target=self._download_worker, args=(url, mode), daemon=True).start()

    def _download_worker(self, url, mode):
        try:
            folder = get_folder(mode)
            path = download(url, mode, folder,
                            lambda p: self.set_status(f"Скачивание: {p:.0f}%"))
            scan_media(path)
            self.set_status(f"Готово!\n{path}")
        except Exception as ex:
            self.set_status(f"Ошибка скачивания: {ex}")
        finally:
            self.busy = False


if __name__ == "__main__":
    MusicApp().run()

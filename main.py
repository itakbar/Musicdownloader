import os
import sys
import threading
import traceback


class _NullOut:
    """Заглушка на случай, если у sys.stdout / sys.stderr нет метода write."""

    def write(self, s):
        return len(s) if s else 0

    def flush(self):
        pass

    def isatty(self):
        return False


for _name in ("stdout", "stderr"):
    if not hasattr(getattr(sys, _name, None), "write"):
        setattr(sys, _name, _NullOut())

try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import platform

from yt_dlp import YoutubeDL

# ---------- Цвета ----------

BG = (0.078, 0.063, 0.122, 1)
CARD = (0.118, 0.094, 0.188, 1)
FIELD = (0.165, 0.133, 0.259, 1)
ACCENT = (1.0, 0.36, 0.54, 1)
ACCENT_DOWN = (0.85, 0.27, 0.44, 1)
SECOND = (0.31, 0.26, 0.50, 1)
SECOND_DOWN = (0.24, 0.20, 0.40, 1)
TEXT = (0.96, 0.95, 0.99, 1)
MUTED = (0.68, 0.64, 0.80, 1)

Window.clearcolor = BG
Window.softinput_mode = "below_target"

SEARCH_LIMIT = 10


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

class QuietLogger:
    """yt-dlp ничего не пишет в stdout/stderr, всё идёт сюда и игнорируется."""

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def base_opts():
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": QuietLogger(),
        "cachedir": False,
        "socket_timeout": 30,
    }


def fmt_duration(sec):
    if not sec:
        return "?"
    sec = int(sec)
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_query(text):
    """Одна строка = название. Несколько строк = кусок текста песни."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return "", False
    if len(lines) == 1:
        return lines[0], False
    return " ".join(lines)[:250] + " lyrics", True


def search(query, limit=SEARCH_LIMIT):
    opts = base_opts()
    opts.update({"extract_flat": True, "skip_download": True})
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    results = []
    for e in info.get("entries", []):
        if not e:
            continue
        vid = e.get("id")
        url = e.get("url") or f"https://www.youtube.com/watch?v={vid}"
        results.append({
            "title": e.get("title", "Без названия"),
            "channel": e.get("channel") or e.get("uploader") or "?",
            "duration": fmt_duration(e.get("duration")),
            "url": url,
            "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg" if vid else "",
        })
    return results


def download(url, mode, folder, on_progress):
    """mode: 'a' = аудио (m4a), 'v' = видео (mp4). Возвращает путь к файлу."""

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                on_progress(d.get("downloaded_bytes", 0) * 100 / total)

    opts = base_opts()
    opts.update({
        "outtmpl": os.path.join(folder, "%(title)s.%(ext)s"),
        "noplaylist": True,
        "progress_hooks": [hook],
        "format": "bestaudio[ext=m4a]/bestaudio" if mode == "a" else "best[ext=mp4]/best",
    })
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        downloads = info.get("requested_downloads") or []
        path = downloads[0].get("filepath") if downloads else None
        return path or ydl.prepare_filename(info)


def short_error(ex):
    """Текст ошибки + файл и строка, где она случилась."""
    where = ""
    try:
        tb = ex.__traceback__
        inner = getattr(ex, "exc_info", None)
        if inner and len(inner) > 2 and inner[2] is not None:
            tb = inner[2]
        frame = traceback.extract_tb(tb)[-1]
        where = f" [{os.path.basename(frame.filename)}:{frame.lineno}]"
    except Exception:
        pass
    return f"{ex}{where}"


# ---------- Виджеты ----------

def label(text="", **kw):
    kw.setdefault("color", TEXT)
    kw.setdefault("halign", "left")
    kw.setdefault("valign", "middle")
    lbl = Label(text=text, **kw)
    lbl.bind(size=lambda inst, s: setattr(inst, "text_size", s))
    return lbl


class Card(BoxLayout):
    """Блок с закруглённым фоном."""

    def __init__(self, bg=CARD, radius=16, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*bg)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size,
                                          radius=[dp(radius)])
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size


class FlatButton(Button):
    """Плоская закруглённая кнопка, темнеет при нажатии."""

    def __init__(self, bg=ACCENT, bg_down=ACCENT_DOWN, **kw):
        kw.setdefault("bold", True)
        kw.setdefault("color", TEXT)
        super().__init__(background_normal="", background_down="",
                         background_color=(0, 0, 0, 0), **kw)
        self._bg = bg
        self._bg_down = bg_down
        with self.canvas.before:
            self._col = Color(*bg)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size,
                                          radius=[dp(10)])
        self.bind(pos=self._sync, size=self._sync, state=self._on_state)

    def _sync(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _on_state(self, _w, state):
        self._col.rgba = self._bg_down if state == "down" else self._bg


# ---------- Приложение ----------

class MusicApp(App):
    def build(self):
        self.title = "Music Downloader"
        self.busy = False

        root = BoxLayout(orientation="vertical",
                         padding=[dp(12), dp(14), dp(12), dp(10)],
                         spacing=dp(10))

        root.add_widget(label("Music Downloader", bold=True, font_size="22sp",
                              color=ACCENT, size_hint_y=None, height=dp(36)))

        field = Card(bg=FIELD, radius=14, size_hint_y=None, height=dp(92),
                     padding=[dp(6), dp(4)])
        self.query = TextInput(
            hint_text="Название песни или несколько строк из её текста",
            multiline=True, write_tab=False,
            background_normal="", background_active="",
            background_color=(0, 0, 0, 0),
            foreground_color=TEXT, hint_text_color=MUTED,
            cursor_color=ACCENT, selection_color=(1.0, 0.36, 0.54, 0.35),
            padding=[dp(8), dp(8)], font_size="16sp",
        )
        field.add_widget(self.query)
        root.add_widget(field)

        find_btn = FlatButton(text="Найти", font_size="17sp",
                              size_hint_y=None, height=dp(48))
        find_btn.bind(on_release=lambda *_: self.start_search())
        root.add_widget(find_btn)

        self.status = label("Введи название или пару строк из песни",
                            color=MUTED, font_size="13sp", max_lines=3,
                            size_hint_y=None, height=dp(52))
        root.add_widget(self.status)

        self.progress = ProgressBar(max=100, value=0,
                                    size_hint_y=None, height=dp(6))
        root.add_widget(self.progress)

        scroll = ScrollView(bar_width=dp(3))
        self.results_box = GridLayout(cols=1, spacing=dp(12), size_hint_y=None,
                                      padding=[0, dp(4)])
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

    def set_progress(self, value):
        Clock.schedule_once(lambda dt: setattr(self.progress, "value", value))

    # --- поиск ---
    def start_search(self):
        q, is_lyrics = build_query(self.query.text)
        if not q:
            return
        self.query.focus = False
        self.results_box.clear_widgets()
        self.set_progress(0)
        self.set_status("Ищу по тексту песни..." if is_lyrics else "Ищу...")
        threading.Thread(target=self._search_worker, args=(q,), daemon=True).start()

    def _search_worker(self, q):
        try:
            results = search(q)
        except Exception as ex:
            self.set_status(f"Ошибка поиска: {short_error(ex)}")
            return
        Clock.schedule_once(lambda dt: self.show_results(results))

    def show_results(self, results):
        self.results_box.clear_widgets()
        if not results:
            self.set_status("Ничего не найдено. Попробуй другие слова.")
            return
        self.set_status(f"Найдено: {len(results)}")
        for r in results:
            self.results_box.add_widget(self.make_card(r))

    def make_card(self, r):
        card = Card(orientation="vertical", size_hint_y=None, height=dp(166),
                    padding=dp(10), spacing=dp(8))

        top = BoxLayout(size_hint_y=None, height=dp(90), spacing=dp(10))
        thumb = AsyncImage(source=r["thumb"], size_hint_x=None, width=dp(160),
                           fit_mode="cover")
        info = BoxLayout(orientation="vertical", spacing=dp(2))
        info.add_widget(label(r["title"], bold=True, font_size="15sp",
                              max_lines=3, valign="top"))
        info.add_widget(label(f"{r['channel']}  |  {r['duration']}",
                              color=MUTED, font_size="12sp",
                              size_hint_y=None, height=dp(20)))
        top.add_widget(thumb)
        top.add_widget(info)
        card.add_widget(top)

        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        a_btn = FlatButton(text="Аудио (m4a)")
        v_btn = FlatButton(text="Видео (mp4)", bg=SECOND, bg_down=SECOND_DOWN)
        a_btn.bind(on_release=lambda _b, u=r["url"]: self.start_download(u, "a"))
        v_btn.bind(on_release=lambda _b, u=r["url"]: self.start_download(u, "v"))
        btns.add_widget(a_btn)
        btns.add_widget(v_btn)
        card.add_widget(btns)
        return card

    # --- скачивание ---
    def start_download(self, url, mode):
        if self.busy:
            self.set_status("Подожди, идёт другая загрузка...")
            return
        self.busy = True
        self.set_progress(0)
        self.set_status("Начинаю скачивание...")
        threading.Thread(target=self._download_worker, args=(url, mode), daemon=True).start()

    def _on_progress(self, p):
        self.set_progress(p)
        self.set_status(f"Скачивание: {p:.0f}%")

    def _download_worker(self, url, mode):
        try:
            folder = get_folder(mode)
            path = download(url, mode, folder, self._on_progress)
            scan_media(path)
            self.set_progress(100)
            self.set_status(f"Готово!\n{path}")
        except Exception as ex:
            self.set_status(f"Ошибка скачивания: {short_error(ex)}")
        finally:
            self.busy = False


if __name__ == "__main__":
    MusicApp().run()

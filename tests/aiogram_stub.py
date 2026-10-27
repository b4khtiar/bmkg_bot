"""Tiruan aiogram untuk lingkungan uji.

aiogram tidak bisa dipasang di lingkungan ini (index paket hanya menyediakan
versi <3.23; membangun aiohttp/pydantic-core di Python 3.15 gagal). Modul ini
memasang paket tiruan yang cukup untuk mengimpor `main` dan `handlers/*` serta
memverifikasi bahwa:

* semua nama yang diimpor benar-benar ada,
* dekorator router mendaftarkan handler yang diharapkan,
* alias perintah lama masih terdaftar.

Stub ini sengaja tidak menyimulasikan Telegram. Perilaku pengiriman diuji
dengan fake bot di `tests/test_broadcast.py`.
"""
import os
import sys
import types as pytypes

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ADMIN_CHAT_ID", "123456")


class Router:
    def __init__(self, *a, **k):
        self.message_handlers = []
        self.callback_handlers = []
        # (handler, filter args, filter kwargs) per registrasi.
        self.registrations = []

    def message(self, *a, **k):
        def deco(f):
            self.message_handlers.append(f)
            self.registrations.append((f, a, k))
            return f
        return deco

    def callback_query(self, *a, **k):
        def deco(f):
            self.callback_handlers.append(f)
            return f
        return deco


class _Filter:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class Bot:
    def __init__(self, *a, **k):
        self.published_commands = []

    async def send_message(self, *a, **k):
        return None

    async def send_photo(self, *a, **k):
        return None

    async def set_my_commands(self, commands, scope=None):
        self.published_commands.append((list(commands), scope))


class Dispatcher:
    def __init__(self, *a, **k):
        self.routers = []

    def include_router(self, router):
        self.routers.append(router)

    async def start_polling(self, bot):
        return None


class TelegramBadRequest(Exception):
    pass


class TelegramAPIError(Exception):
    pass


class BotCommand:
    def __init__(self, command=None, description=None, **k):
        self.command = command
        self.description = description


class BotCommandScopeChat:
    def __init__(self, chat_id=None, **k):
        self.chat_id = chat_id


class InlineKeyboardButton:
    def __init__(self, text=None, callback_data=None, **k):
        self.text = text
        self.callback_data = callback_data


class InlineKeyboardBuilder:
    """Mendekati aiogram cukup untuk menguji tata letak keyboard.

    Yang penting dimodelkan: `button()` menambah tombol datar, `row()` memaksa
    baris baru, dan `adjust(n)` mengubah lebar baris. Tanpa itu, tes tidak
    bisa membedakan "dua provinsi per baris" dari "satu per baris" — dan
    именно masalah yang seharusnya diperbaiki.
    """

    def __init__(self):
        self._items = []
        self._forced = set()
        self._starts = set()
        self._rows = None
        self._width = 1

    def button(self, text=None, callback_data=None, **k):
        b = InlineKeyboardButton(text=text, callback_data=callback_data)
        self._items.append(b)
        self._rows = None
        return b

    def row(self, *buttons, **k):
        # row() memulai baris baru: di aiogram asli, pemanggilan row() setelah
        # adjust() TIDAK menempelkan tombolnya ke baris sisa hasil adjust —
        # misalnya 5 tombol data + row(back) = baris ke-3 berisi 1 tombol dan
        # baris ke-4 berisi back, bukan [tombol5, back].
        self._starts.add(len(self._items))
        for b in buttons:
            self._items.append(b)
        self._forced.add(len(self._items))
        self._rows = None

    def adjust(self, width=None, *a, **k):
        self._width = width or 1
        self._rows = None
        return self

    def _layout(self):
        rows = []
        current = []
        for idx, b in enumerate(self._items):
            if current and idx in self._starts:
                rows.append(current)
                current = []
            current.append(b)
            if (idx + 1) in self._forced or len(current) >= self._width:
                rows.append(current)
                current = []
        if current:
            rows.append(current)
        return rows

    def as_markup(self):
        if self._rows is None:
            self._rows = self._layout()
        return {"inline_keyboard": self._rows}


class Message:
    def __init__(self, *a, **k):
        self.chat = pytypes.SimpleNamespace(id=1)
        self.from_user = pytypes.SimpleNamespace(username="u", id=1)
        self.text = None

    async def answer(self, *a, **k):
        return self

    async def edit_text(self, *a, **k):
        return self


class CallbackQuery:
    def __init__(self, *a, **k):
        self.message = Message()
        self.data = ""
        self.from_user = pytypes.SimpleNamespace(id=1)

    async def answer(self, *a, **k):
        return None

    async def edit_text(self, *a, **k):
        return None


class _MagicNode:
    """Attr accessowy yang bisa dirangkai: `F.data.startswith("x")`."""

    def __init__(self, path=""):
        self.path = path

    def __getattr__(self, name):
        return _MagicNode(f"{self.path}.{name}")

    def __call__(self, *a, **k):
        return _MagicNode(f"{self.path}()")

    def __eq__(self, other):
        return _MagicNode(f"{self.path}==")

    def startswith(self, *a, **k):
        return _MagicNode(f"{self.path}.startswith")

    def __hash__(self):
        return hash(self.path)

    def __repr__(self):
        return f"<Magic {self.path}>"


def _magic_filter():
    return _MagicNode("F")


def install():
    """Pasang modul aiogram/apscheduler tiruan ke sys.modules."""
    def stub(name, **attrs):
        m = pytypes.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    stub(
        "aiogram",
        Router=Router,
        Bot=Bot,
        Dispatcher=Dispatcher,
        types=pytypes.SimpleNamespace(
            Message=Message,
            CallbackQuery=CallbackQuery,
            InlineKeyboardButton=InlineKeyboardButton,
        ),
        F=_magic_filter(),
    )
    stub("aiogram.filters", CommandStart=_Filter, Command=_Filter)
    stub(
        "aiogram.exceptions",
        TelegramBadRequest=TelegramBadRequest,
        TelegramAPIError=TelegramAPIError,
    )
    stub("aiogram.types", Message=Message, CallbackQuery=CallbackQuery,
         InlineKeyboardButton=InlineKeyboardButton, BotCommand=BotCommand,
         BotCommandScopeChat=BotCommandScopeChat)
    stub("aiogram.utils")
    stub("aiogram.utils.keyboard", InlineKeyboardBuilder=InlineKeyboardBuilder)
    stub(
        "apscheduler.schedulers.asyncio",
        AsyncIOScheduler=type("Sched", (), {"__init__": lambda s, **k: None}),
    )

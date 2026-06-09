"""Иконка в системном трее (pystray)."""

import logging
import os

import pystray
from PIL import Image, ImageDraw

from jarvis import APP_NAME, __version__, actions

log = logging.getLogger("jarvis.tray")


def _make_icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=(18, 32, 58, 255), outline=(86, 156, 255, 255), width=3)
    # стилизованная «J»
    d.line((38, 16, 38, 42), fill=(86, 156, 255, 255), width=6)
    d.arc((20, 30, 42, 52), start=20, end=180, fill=(86, 156, 255, 255), width=6)
    return img


def build_tray(jarvis) -> pystray.Icon:
    def on_toggle(icon, item):
        jarvis.listening_enabled = not jarvis.listening_enabled
        log.info("Прослушивание: %s", jarvis.listening_enabled)

    def on_screenshot(icon, item):
        actions.take_screenshot()

    def on_config(icon, item):
        os.startfile(jarvis.base_dir / "config.json")

    def on_log(icon, item):
        os.startfile(jarvis.base_dir / "jarvis.log")

    def on_exit(icon, item):
        jarvis.shutdown()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(f"{APP_NAME} v{__version__}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Слушать микрофон", on_toggle,
                         checked=lambda item: jarvis.listening_enabled),
        pystray.MenuItem("Сделать скриншот", on_screenshot),
        pystray.MenuItem("Открыть конфиг", on_config),
        pystray.MenuItem("Открыть журнал", on_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", on_exit),
    )
    return pystray.Icon("jarvis", _make_icon_image(), f"{APP_NAME} v{__version__}", menu)

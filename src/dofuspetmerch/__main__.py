"""Entry point: ``python -m dofuspetmerch [--debug] [--read IMG] [--capture-test]``."""
from __future__ import annotations

import argparse
import sys


def _cli() -> None:
    from .reading.capture import enable_dpi_awareness

    enable_dpi_awareness()  # must happen before any window / capture
    ap = argparse.ArgumentParser(prog="DofusPetMerch", description="Lector pasivo de precios del mercadillo de Dofus")
    ap.add_argument("--debug", action="store_true", help="guarda capturas y OCR en %%APPDATA%%\\dofuspetmerch\\debug")
    ap.add_argument("--read", metavar="IMG", help="analiza una captura guardada y muestra el resultado en consola")
    ap.add_argument("--capture-test", action="store_true", help="captura la ventana de Dofus y la guarda en un PNG")
    a = ap.parse_args()

    if a.read or a.capture_test:
        _console(a)
        return
    from .ui.app import main

    main(debug=a.debug)


def _console(a) -> None:
    from . import imgutil
    from .analysis import analyze
    from .parsing import format_kamas, format_unit, format_xp
    from .paths import app_dir
    from .reading.ocr import WinOcr
    from .settings import Settings
    from .xptable import XpTable

    if sys.stdout is None:  # windowed exe: print to the terminal that launched us, if any
        import ctypes

        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8")
            sys.stderr = sys.stdout
            print()
        else:
            sys.stdout = open(app_dir() / "last_output.txt", "w", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if a.capture_test:
        from .reading.capture import capture

        img, rect, src = capture(Settings.load().window_title)
        out = app_dir() / "capture_test.png"
        imgutil.save(out, img)
        print(f"Capturado {src} {rect} -> {out}")
        return
    img = imgutil.load(a.read)
    if img is None:
        sys.exit(f"No se pudo abrir {a.read}")
    s = Settings.load()
    data = analyze(img, s, XpTable.load(), WinOcr(s.lang), debug=s.debug or a.debug)
    if data.error:
        print("ERROR:", data.error)
        return
    print(f"Objeto: {data.name}")
    if data.max_unit is not None:
        print(f"XP/u: {format_xp(data.item_xp)}  ->  Máx. rentable: {format_unit(data.max_unit)} K/u")
        for e in data.evals:
            print(f"  lote {e.lot:>5}: {format_kamas(e.price):>8} K  ({format_unit(e.unit_price)} K/u, máx {format_kamas(e.max_lot_price)})  {'RENTABLE' if e.profitable else 'no'}")
    else:
        print("XP desconocida (añádela en la tabla XP)")
        for lot, price in data.rows:
            print(f"  lote {lot:>5}: {format_kamas(price):>8} K")
    for w in data.warnings:
        print("aviso:", w)


if __name__ == "__main__":
    _cli()

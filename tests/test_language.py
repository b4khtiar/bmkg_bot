"""Konsistensi bahasa dan nada di seluruh teks yang dilihat pengguna.

Tiga kelas pengguna melihat bahasa berbeda dalam satu bot yang sama:
*orang tetap memakai "Anda" di welcome dan panel admin, sementara sisanya
"kamu" di insight dan /notifikasi; dan prefiks insight ("Saran hari ini:")
mencampur keduanya dalam satu pool*, jadi pesan yang sama bisa formal atau
santai tergantung undian. Reg Checking ini menjaga pilihan itu tetap
konsisten tanpa memindai seluruh isi emoji.
"""
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

# File yang berisi teks aimed-at end-user. Komentar dan log tidak ikutbecause
# dokumentasi internal boleh campur bahasa.
USER_FACING = [
    "handlers/user.py",
    "handlers/admin.py",
    "utils/formatters.py",
    "utils/design.py",
    "utils/keyboards.py",
    "utils/insight_templates.py",
]

# Kata sapaan yang tidak konsisten. "Anda" adalah bentuk yang dipakai di
# welcome, pesan error, dan panel admin.
INFORMAL = re.compile(r"\b(kamu|kalian|gua|lo)\b", re.IGNORECASE)


def _strip_comments_and_docstrings(source: str) -> list[str]:
    """Kembalikan hanya baris kode, tanpa komentar dan docstring.

    Dokumentasi internal boleh campur bahasa; yang diuji adalah string yang
    benar-benar sampai ke pengguna.
    """
    code_lines = []
    in_doc = False
    for line in source.splitlines():
        stripped = line.strip()
        if in_doc:
            if '"""' in stripped:
                in_doc = False
            continue
        if stripped.startswith('"""'):
            if stripped.count('"""') == 1:
                in_doc = True
            continue
        if stripped.startswith("#"):
            continue
        code_lines.append(line.split("  #")[0])
    return code_lines


@pytest.mark.parametrize("relpath", USER_FACING)
def test_no_informal_second_person(relpath):
    """'kamu' tidak boleh muncul di teks pengguna; pakai 'Anda'."""
    lines = _strip_comments_and_docstrings(
        (SRC / relpath).read_text(encoding="utf-8")
    )
    hits = [
        (i + 1, m.group(0))
        for i, l in enumerate(lines)
        for m in INFORMAL.finditer(l)
        # Baris log dan exception tidak pernah dikirim ke pengguna.
        if "logger." not in l
    ]
    assert not hits, f"{relpath} memakai sapaan tidak konsisten: {hits}"


@pytest.mark.parametrize("relpath", USER_FACING)
def test_html_is_the_only_parse_mode(relpath):
    """Semua pesan pakai HTML.

    Markdown masih tersisa di dua handler (welcome /start dan pesan error
    whitelist), sehingga formatting yang sama terender berbeda tergantung
    konteksnya.
    """
    source = (SRC / relpath).read_text(encoding="utf-8")
    assert 'parse_mode="Markdown"' not in source, (
        f"{relpath} masih memakai parse_mode Markdown"
    )


@pytest.mark.parametrize("relpath", USER_FACING)
def test_no_mixed_dash_styles(relpath):
    """Satu keluarga garis pemisah untuk seluruh bot."""
    source = (SRC / relpath).read_text(encoding="utf-8")
    # "━━━" dan "━━━━" sama-sama U+2501, jadi keduanya satu keluarga. Yang
    # dilarang adalah U+2500 (─), yang sebelumnya bercampur dengan U+2501.
    assert "─" not in source, f"{relpath} memakai gaya garis lain (U+2500)"
    assert "═" not in source, f"{relpath} memakai gaya garis lain (U+2550)"


def test_pick_present_markers_are_consistent():
    """Tanda aktif/nonaktif harus satu konvensi di seluruh bot."""
    keyboards = (SRC / "utils/keyboards.py").read_text(encoding="utf-8")
    # "✅" untuk aktif; tidak ada lingkaran berwarna sebagai penanda state,
    # karena 🟤 (cokelat) tidak terbaca dan terlihat seperti glitch.
    assert "✅" in keyboards
    assert "🟤" not in keyboards
    assert "🟠 Gempa" not in keyboards


@pytest.mark.parametrize("relpath", ["utils/design.py", "utils/formatters.py"])
def test_one_rule_glyph_family_across_renderers(relpath):
    """U+2501 hanya. Gaya lama bercampur: '━━━', '━━━━', dan tanpa pemisah."""
    source = (SRC / relpath).read_text(encoding="utf-8")
    assert "─" not in source and "═" not in source


def test_severity_labels_are_uppercase_everywhere():
    """'Bahaya' vs 'BAHAYA' duduk berdampingan dengan bobot berbeda."""
    design = (SRC / "utils/design.py").read_text(encoding="utf-8")
    for label in ("BAHAYA", "WASPADA", "SIAGA", "INFO"):
        assert f'"{label}"' in design

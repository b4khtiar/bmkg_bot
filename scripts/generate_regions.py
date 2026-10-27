"""Generate modul data wilayah provinsi dari dataset kode wilayah publik.

Dev-only, tidak dikumpulkan pytest (bukan test_*.py). Sumber:
vermaysha/database-wilayah-indonesia (mirror JSON dari cahyadsn/wilayah,
Kepmendagri), diambil ke /tmp/opencode/{regency,village}.json secara manual.

Pemakaian:
    .venv/bin/python scripts/generate_regions.py [DIR_JSON] [DIR_OUT]

Label output: "{Desa}, Kab. X" / "{Desa}, Kota X" — tipe "Kabupaten ..." /
"Kota (Administrasi) ..." disederhanakan menjadi "Kab. X" / "Kota X", karena
kata "Administrasi" tidak membantu pengguna Telegram memilih lokasi.
"""
import json
import sys

#: (prefix adm4, provinsi name, nama modul) sesuai PROVINCE_MAP/utils.constants.
JAVA = [
    ("31", "DKI Jakarta", "dki"),
    ("32", "Jawa Barat", "jawa_barat"),
    ("33", "Jawa Tengah", "jawa_tengah"),
    ("34", "DI Yogyakarta", "diy"),
    ("35", "Jawa Timur", "jawa_timur"),
    ("36", "Banten", "banten"),
]

SOURCE_NOTE = (
    "Sumber kode wilayah: Kepmendagri — kode wilayah administrasi tingkat IV\n"
    "(adm4, format yang sama dengan yang diminta API BMKG) — lewat mirror JSON\n"
    "https://github.com/vermaysha/database-wilayah-indonesia, yang sendiri\n"
    "dikonversi dari https://github.com/cahyadsn/wilayah. Digenerate oleh\n"
    "scripts/generate_regions.py.\n"
)


def regency_label(reg_name: str) -> str:
    """"Kabupaten Bogor" -> "Kab. Bogor"; "Kota Administrasi Jakarta Timur"
    -> "Kota Jakarta Timur" — kata "Administrasi" tidak berguna di tombol
    keyboard 30 karakter."""
    for prefix, short in (("Kabupaten Administrasi ", "Kab. "),
                          ("Kota Administrasi ", "Kota "),
                          ("Kabupaten", "Kab. "),
                          ("Kota", "Kota ")):
        if reg_name.startswith(prefix):
            return short + reg_name[len(prefix):].strip()
    raise ValueError(f"tipe regency haruspun Kabupaten/Kota, dapat: {reg_name!r}")


def main(src_dir, out_dir):
    regs = {r["regency_id"]: r["regency_name"]
            for r in json.load(open(f"{src_dir}/regency.json"))}

    for prefix, prov, module in JAVA:
        desas = sorted(
            (v["village_id"], v["village_name"])
            for v in json.load(open(f"{src_dir}/village.json"))
            if v["province_id"] == prefix
        )
        region = {
            f"{cid[:2]}.{cid[2:4]}.{cid[4:6]}.{cid[6:]}":
                f"{name}, {regency_label(regs[cid[:4]])}"
            for cid, name in desas
        }
        assert len(region) == len(desas), "kode adm4 duplikat"

        body = json.dumps(region, ensure_ascii=False, indent=8, sort_keys=False)
        # rapikan ke bentuk dict literal Python
        body = body.replace("true", "True").replace("null", "None")
        module_content = (
            f'"""{prov} — kode adm4 dan label tampilan.\n\n'
            + SOURCE_NOTE +
            f'\nJumlah entri: {len(region)}.\n'
            '"""\n\n'
            f'REGION_DATA = {{\n    "{prov}": {body},\n}}\n'
        )
        with open(f"{out_dir}/{module}.py", "w") as f:
            f.write(module_content)
        print(f"{module}.py: {len(region)} entri")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/opencode"
    out = sys.argv[2] if len(sys.argv) > 2 else "src/utils/regions"
    main(src, out)

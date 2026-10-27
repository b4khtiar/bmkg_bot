"""Validasi live: kode adm4 di REGION_DATA vs yang diterima API BMKG.

Dev-only, tidak dikumpulkan pytest (bukan test_*.py; pytest tidak pernah
menyentuh jaringan). Rate-limited di bawah batas dokumen BMKG
(60 permintaan/menit per IP), default lebih rendah supaya aman.

Penting soal "lubang": grid BMKG di-regenerate dua kali sehari, dan kode yang
sama bisa 404 di satu jendela waktu lalu 200 di jendela berikutnya. Karena itu
kode yang mencurigakan SELALU diulang di jendela waktu terpisah; hanya kode
yang gagal di SEMUA jendela dilaporkan sebagai lubang yang bertahan. Jangan
pernah memfilter REGION_DATA berdasarkan satu sesi validasi.

Pemakaian:
    .venv/bin/python scripts/validate_regions.py [--sample N] [--rate PERM]
        [--windows N] [--gap S] [--seed S] [--provinces P1,P2]

--sample 0 = hanya desa pertama tiap kabupaten/kota. Keluaran: ringkasan
cakupan + daftar lubang yang bertahan. Exit code 0 kecuali lubang permanen
menutupi >1% sampel — itu sinyal untuk menyelidiki, bukan dasar memfilter
data.
"""
import argparse
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.regions import REGION_DATA  # noqa: E402

API = "https://api.bmkg.go.id/publik/prakiraan-cuaca"


def regency_heads(data):
    """Desa pertama tiap kabupaten/kota (lima digit pertama), lintas provinsi."""
    heads = []
    for prov, places in data.items():
        seen = set()
        for code in sorted(places):
            head = code[:5]
            if head in seen:
                continue
            seen.add(head)
            heads.append((code, places[code]))
    return heads


def check(client, code, label):
    """None kalau OK, string penyebab kalau tidak."""
    try:
        r = client.get(API, params={"adm4": code})
    except httpx.HTTPError as e:
        return f"EXC {type(e).__name__}"
    if r.status_code != 200:
        return f"HTTP {r.status_code}"
    lok = r.json()["data"][0]["lokasi"]
    ours = label.partition(",")[0].strip().casefold()
    if lok["desa"].casefold().strip() != ours:
        return f"NAMA bmkg={lok['desa']!r}"
    return None


def run_window(client, items, rate):
    """Satu jendela validasi; kembalikan {kode: (label, alasan)} yang gagal."""
    delay = 60.0 / rate
    bad = {}
    for i, (code, label) in enumerate(items):
        reason = check(client, code, label)
        if reason:
            bad[code] = (label, reason)
        time.sleep(delay)
        if (i + 1) % 25 == 0:
            print(f"  ...{i + 1}/{len(items)}", flush=True)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=400,
                    help="jumlah kode acak tambahan (0 = desa pertama per kab/kota)")
    ap.add_argument("--rate", type=int, default=50,
                    help="maksimum permintaan per menit (batas BMKG: 60)")
    ap.add_argument("--windows", type=int, default=3,
                    help="berapa jendela waktu pembandingan ulang")
    ap.add_argument("--gap", type=int, default=90,
                    help="detik istirahat antar jendela")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--provinces", type=str, default="",
                    help="filter nama provinsi, dipisah koma")
    args = ap.parse_args()

    data = REGION_DATA
    if args.provinces:
        wanted = {p.strip() for p in args.provinces.split(",") if p.strip()}
        data = {p: v for p, v in REGION_DATA.items() if p in wanted}
        if not data:
            print("tidak ada provinsi yang cocok:", args.provinces)
            return 2

    # Ringkasan cakupan selalu dari pustaka penuh, bukan dari sampel yang
    # mungkin difilter provinsi.
    per_prov = {p: len(v) for p, v in REGION_DATA.items()}
    total = sum(per_prov.values())

    sample = regency_heads(data)
    heads_n = len(sample)

    if args.sample:
        rng = random.Random(args.seed)
        pool = [(c, l) for p in data for c, l in data[p].items()]
        seen_codes = {c for c, _ in sample}
        extra = [t for t in rng.sample(pool, min(args.sample, len(pool)))
                 if t[0] not in seen_codes]
        sample = sample + extra

    dur = len(sample) / max(1, args.rate)
    print(f"sample: {heads_n} kepala kab/kota + {len(sample) - heads_n} acak "
          f"= {len(sample)} kode; ~{dur:.0f} menit per jendela pada "
          f"{args.rate} perm/menit; maks {args.windows} jendela")
    print("pustaka:", total, "entri;",
          ", ".join(f"{p} {n}" for p, n in per_prov.items()))

    # Lubang bertahan = irisan fail-set semua jendela yang berjalan — kode
    # yang lolos di jendela mana pun otomatis keluar dari daftar. Tidak jalan
    # jendela kedua (jendela pertama bersih) berarti irisannya kosong.
    fail_sets = []
    last_bad = {}
    items = sample
    for w in range(1, args.windows + 1):
        if w > 1:
            print(f"jendela {w}: tunggu {args.gap}s lalu ulangi "
                  f"{len(items)} kode mencurigakan", flush=True)
            time.sleep(args.gap)
        with httpx.Client(timeout=15.0) as client:
            bad = run_window(client, items, args.rate)
        fail_sets.append(set(bad))
        last_bad = bad
        print(f"jendela {w}: {len(items)} dicek, "
              f"{len(items) - len(bad)} lolos ({len(bad)} dicurigai)")
        # Jendela berikutnya hanya menerima (kode, label) — alasan per kode
        # sudah terekam di last_bad, dan label itu sendiri tetap bersih.
        items = [(c, lr[0] if isinstance(lr, tuple) else lr)
                 for c, lr in bad.items()]
        if not bad:
            break

    persistent = set(fail_sets[0])
    for s in fail_sets[1:]:
        persistent &= s

    print()
    print("== HASIL ==")
    if persistent:
        by_reason = defaultdict(list)
        for code in persistent:
            label, reason = last_bad.get(code, ("?", "?"))
            by_reason[reason.split(" ")[0]].append((code, label, reason))
        for reason, entries in sorted(by_reason.items()):
            print(f"{reason}: {len(entries)}")
            for code, label, r in sorted(entries)[:20]:
                print(f"  {code}  {label}  ({r})")
        pct = len(persistent) / len(sample) * 100
        print(f"persentase: {pct:.2f}% dari sampel ({len(sample)} kode)")
        if pct > 1.0:
            print("PERHATIAN: >1% — selidiki; jangan langsung memfilter data")
            return 1
    else:
        print("bersih: seluruh sampel diterima BMKG dengan nama yang cocok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

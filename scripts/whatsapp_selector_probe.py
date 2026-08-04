"""Periksa selector panggilan WhatsApp terhadap DOM sungguhan. READ-ONLY.

Fase 13 membuat `start_call` menuntut BUKTI sebelum mengaku menelepon, tetapi
selectornya belum pernah diuji terhadap WhatsApp Web asli. Label bukti repo
untuk itu adalah `focused-tested`, BUKAN `live-proven` — "LIVE-PROVEN" pada
commit CLK `987864e` adalah tone loopback, bukan DOM panggilan.

Risikonya berbalik arah: bila overlay asli tidak cocok dengan
`_HANGUP_SELECTORS`/`_RINGING_SELECTORS` dalam 8 detik, setiap panggilan nyata
dilaporkan "tidak terbukti" padahal mungkin sedang berdering.

Skrip ini TIDAK PERNAH mengklik apa pun dan tidak pernah memulai panggilan.
Ia hanya membaca halaman dan melaporkan selector mana yang cocok, plus
kandidat aria-label yang terlihat supaya selector bisa diperbaiki bila meleset.

Pakai:
    # 1) tanpa panggilan — memvalidasi tombol panggilan saja
    python scripts/whatsapp_selector_probe.py

    # 2) SAAT panggilan sungguhan sedang berdering/aktif (dimulai MANUAL oleh
    #    Takeda dari jendela WhatsApp), untuk memvalidasi bukti Fase 13
    python scripts/whatsapp_selector_probe.py --during-call
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.integrations import whatsapp_web as ww  # noqa: E402

_GROUPS = {
    "ready": ww._READY_SELECTORS,
    "call_button": ww._CALL_SELECTORS,
    "answer": ww._ANSWER_SELECTORS,
    "hangup": ww._HANGUP_SELECTORS,
    "ringing": ww._RINGING_SELECTORS,
}

# Dibaca hanya untuk melaporkan kandidat saat selector kita meleset.
_CANDIDATE_JS = """
() => {
  const out = [];
  for (const el of document.querySelectorAll(
        'button,[role="button"],[data-icon],[aria-label]')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const label = (el.getAttribute('aria-label') || '').trim();
    const icon = (el.getAttribute('data-icon') || '').trim();
    const title = (el.getAttribute('title') || '').trim();
    if (!label && !icon && !title) continue;
    const text = (label + ' ' + icon + ' ' + title).toLowerCase();
    if (!/call|panggil|telep|hang|end|akhiri|answer|jawab|angkat|ring|dering|video|suara|voice/
          .test(text)) continue;
    out.push({aria_label: label, data_icon: icon, title: title,
              tag: el.tagName.toLowerCase()});
    if (out.length >= 25) break;
  }
  return out;
}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--during-call", action="store_true",
        help="jalankan saat panggilan sungguhan sedang berlangsung")
    parser.add_argument(
        "--contact", default="",
        help="buka chat kontak allowlist lewat NAVIGASI agar tombol panggilan "
             "terlihat; tidak pernah mengklik dan tidak pernah mengirim pesan")
    args = parser.parse_args()

    if not ww.available():
        print("WhatsApp Web tidak aktif atau Playwright tidak terpasang.")
        return 2

    service = ww.WhatsAppWebService.get()

    def probe(page) -> dict:
        # Tombol panggilan hanya ada DI DALAM chat, dan halaman butuh waktu
        # memuat. Tanpa dua hal ini probe melaporkan "TIDAK COCOK" yang
        # menyesatkan — selectornya belum tentu salah, halamannya saja belum
        # siap.
        deadline = 60
        while deadline > 0 and ww._first_visible(page, ww._READY_SELECTORS) is None:
            page.wait_for_timeout(1000)
            deadline -= 1
        opened = ""
        if args.contact and ww._first_visible(page, ww._READY_SELECTORS):
            try:
                contact = ww.resolve_contact(args.contact)
                # Navigasi, BUKAN klik. Tidak ada pesan yang dikirim.
                ww.WhatsAppWebService._open_chat(page, contact)
                opened = contact.name
                page.wait_for_timeout(1500)
            except Exception as exc:                         # noqa: BLE001
                opened = f"gagal: {type(exc).__name__}: {str(exc)[:120]}"

        matched = {
            name: [selector for selector in selectors
                   if ww._first_visible(page, (selector,)) is not None]
            for name, selectors in _GROUPS.items()
        }
        try:
            candidates = page.evaluate(_CANDIDATE_JS)
        except Exception as exc:                             # noqa: BLE001
            candidates = [{"error": f"{type(exc).__name__}: {exc}"}]
        return {
            "url": str(page.url),
            "chat_opened": opened,
            "status_state": ww.WhatsAppWebService._status_on_page(page)["state"],
            "matched": matched,
            "call_ui_candidates": candidates,
        }

    result = service._call(probe, timeout=90)
    print(json.dumps(result, indent=1, ensure_ascii=False))

    matched = result["matched"]
    print("\n--- PENILAIAN ---")
    print(f"state         : {result['status_state']}")
    print(f"tombol call   : {'COCOK' if matched['call_button'] else 'TIDAK COCOK'}")
    if args.during_call:
        proven = bool(matched["hangup"] or matched["ringing"])
        print(f"bukti panggilan: {'COCOK' if proven else 'TIDAK COCOK'}"
              f"  (hangup={len(matched['hangup'])}, "
              f"ringing={len(matched['ringing'])})")
        if not proven:
            print("\nSELECTOR BUKTI MELESET. Panggilan nyata akan dilaporkan")
            print("'tidak terbukti'. Pakai call_ui_candidates di atas untuk")
            print("memperbaiki _HANGUP_SELECTORS / _RINGING_SELECTORS.")
            return 1
    else:
        print("bukti panggilan: tidak diuji — ulangi dengan --during-call "
              "saat panggilan sungguhan sedang berlangsung")
    return 0 if matched["call_button"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

# DIAGNOSIS 2 — lima masalah yang dilaporkan user

Diagnosis saja. **Nol baris kode diubah.** Semua klaim membawa `file:baris`.

| | |
|---|---|
| **Tanggal** | 2026-07-27 |
| **Metode** | Pembacaan kode + menjalankan router nyata pada kalimat asli |
| **Verifikasi** | `IntentRouter._rules()` dieksekusi langsung (bukan dibaca saja) |

---

## MASALAH 3 — "tutup aplikasi instagram" menutup JARVIS 🔴

### VERDICT: **TERBUKTI**, dan lebih buruk dari hipotesis

Hipotesis menyebut tiga kemungkinan penyebab. Kenyataannya **ketiganya ada
sekaligus**, ditambah satu yang tidak disebut: jalur aman sudah dibangun tetapi
tidak terjangkau dari suara.

### 3a. Tidak ada tool yang menutup aplikasi *bernama*

Yang ada hanya ini (`actions/computer_settings.py:174-180`):

```python
def close_app():
    if _OS == "Darwin": pyautogui.hotkey("command", "q")
    else:               pyautogui.hotkey("alt", "f4")

def close_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "w")
    else:               pyautogui.hotkey("ctrl", "w")
```

**Tidak menerima parameter apa pun.** Ia menekan Alt+F4 ke **jendela yang
sedang fokus**. Kalau jendela Jarvis yang fokus — dan itu wajar, karena user
baru saja bicara ke Jarvis — maka Jarvis yang tertutup.

Terdaftar di `ACTION_MAP` sebagai `"close_app"` (`computer_settings.py:521`).

### 3b. `close_app` TIDAK termasuk aksi berbahaya

`actions/computer_settings.py:571`:

```python
_DANGEROUS_ACTIONS = {"restart", "shutdown"}
```

Gerbang konfirmasi di `:638-643` hanya berlaku untuk kedua nama itu. Menutup
aplikasi — termasuk menutup Jarvis sendiri — **berjalan tanpa konfirmasi**.

### 3c. Pemilihan aksi diserahkan ke LLM kedua, dengan instruksi "tebak saja"

`computer_settings()` menerima `description` bebas lalu memanggil `_detect_action`
(`computer_settings.py:575-607`), yang bertanya ke Gemini:

```
Available actions: {available}          # seluruh kunci ACTION_MAP
...
- If no clear match, pick the closest action.
```

`actions/computer_settings.py:598` — **"pick the closest action"** adalah
instruksi yang secara aktif mendorong tebakan. Untuk "tutup aplikasi instagram",
`close_app` adalah tebakan terdekat yang tersedia.

> **Koreksi audit sebelumnya.** Di `AUDIT_FINDINGS_CODE.md` §8 (temuan S7) saya
> menyatakan `model="gemini-3.5-flash"` di `actions/desktop.py:144` adalah id
> model tidak valid sehingga jalur itu "rusak". **Itu salah.** Id yang sama
> dipakai `config.yaml:295-296` sebagai `llm.text_model` dan `classify_model` —
> ini model teks standar proyek. `_detect_action` (`computer_settings.py:602`)
> memakainya juga dan **berfungsi**. Konsekuensinya S7 lebih serius dari yang
> saya tulis, bukan kurang.

### 3d. `shutdown_jarvis` — tanpa konfirmasi, tanpa penjaga, bersaing untuk kalimat yang sama

Deklarasi (`main.py:436-448`):

```python
"description": (
    "Shuts down the assistant completely. "
    "Call this when the user expresses intent to end the conversation, "
    "close the assistant, say goodbye, or stop Jarvis. "
    "The user can say this in ANY language."
),
```

*"close the assistant"* + *"ANY language"* membuat kata Indonesia **"tutup"**
menjadi kandidat langsung. Tidak ada parameter, jadi model tidak perlu menyebut
target apa pun untuk memanggilnya.

Eksekusinya (`main.py:966-973`):

```python
elif name == "shutdown_jarvis":
    self.ui.write_log("SYS: Shutdown requested.")
    self.speak("Goodbye, sir.")
    def _shutdown():
        import time, os
        time.sleep(1)
        os._exit(0)
    threading.Thread(target=_shutdown, daemon=True).start()
```

Tanpa konfirmasi. `os._exit(0)` melewati seluruh cleanup — SQLite tidak
di-flush, kamera tidak dilepas, thread tidak di-join. (Ini temuan L-2 audit,
kini terbukti punya jalur pemicu yang realistis.)

### 3e. Jalur AMAN sudah ada — tapi hanya untuk ketikan

`jarvis/core/router.py:130-134` justru sudah menyelesaikan masalah ini:

```python
    # redesign §13 — destructive-action target resolver: a NAMED close
    # target routes through jarvis.core.target_resolver instead of the
    # blind alt+F4 close_app fallback (vision/tab close above still win —
    # this pattern is listed after them so those specific cases match first).
    (re.compile(r"^(?:tolong\s+)?(?:tutup|close)\s+(?P<value>.+)$", re.I), "close_target"),
```

→ `jarvis/core/window_controls.py` → `jarvis/core/target_resolver.py`, yang
melakukan revalidasi target dan `WM_CLOSE` yang sopan
(`target_resolver.py:121-138`).

**Masalahnya: lane suara tidak pernah melewati `IntentRouter`.** Diverifikasi —
`rg "IntentRouter" main.py` → nol hasil. Pemakainya hanya
`jarvis/ui/window.py:276` (ketikan) dan `telegram_light.py:34,148`.

### 3f. Jalur nyata, langkah demi langkah

**Ketikan** — aman:

```
"tutup aplikasi instagram"
  → window.py:276  IntentRouter.classify
  → router.py:134  SYSTEM {action: close_target, value: "aplikasi instagram"}   [diverifikasi]
  → window_controls → target_resolver.close_window()  ← revalidasi + WM_CLOSE
```

**Suara** — berbahaya:

```
"tutup aplikasi instagram"
  → Gemini Live memilih dari 21 TOOL_DECLARATIONS
  → kandidat: computer_settings (main.py:263 "closing apps")
              atau shutdown_jarvis (main.py:441 "close the assistant")
  → computer_settings(description="tutup aplikasi instagram")
  → _detect_action  (computer_settings.py:575)  "pick the closest action"
  → "close_app"     (ACTION_MAP :521)
  → close_app()     (:174) → pyautogui.hotkey("alt","f4")
  → JENDELA FOKUS TERTUTUP — kemungkinan besar Jarvis
```

### 3g. ⚠️ Penjaga proses-sendiri: **TIDAK ADA SAMA SEKALI**

```
rg -n "getpid|current_process|self_pid" --type py (tanpa tests/)  →  NOL HASIL
```

Tidak ada satu pun perbandingan `os.getpid()`, pengecekan nama proses, atau
denylist di seluruh kode. Lebih jauh, jalur paling kuat pun tidak dijaga —
`target_resolver.py:130-134`:

```python
            if force:
                pid = self._pid_for(win.handle)
                if pid:
                    import psutil
                    psutil.Process(pid).terminate()
```

`psutil.Process(pid).terminate()` **tanpa membandingkan `pid` dengan
`os.getpid()`**. Kalau jendela yang diresolusi kebetulan milik Jarvis, Jarvis
mematikan dirinya sendiri — bahkan lewat jalur yang dianggap aman.

Hal serupa berlaku untuk `process_kill` (`jarvis/agent/tools/terminal.py:121-132`).

**Ini yang harus dibangun.**

### 3h. Temuan tambahan: kata sapaan mematahkan jalur aman

Diverifikasi dengan menjalankan router:

| Kalimat | Hasil |
|---|---|
| `tutup aplikasi instagram` | `SYSTEM {close_target}` ✅ aman |
| `tutup instagram` | `SYSTEM {close_target}` ✅ aman |
| **`jarvis tutup aplikasi instagram`** | **`CHAT`** ❌ jatuh ke LLM |

Regex `close_target` di-anchor `^`, sehingga awalan "jarvis" — cara paling
alami orang bicara ke asisten — **membatalkan seluruh jalur aman**.

### Perbaikan minimal yang saya usulkan (JANGAN dikerjakan dulu)

1. **Penjaga proses-sendiri, satu tempat.** Helper `is_self_process(pid)` /
   `is_self_window(win)`, dipanggil di `target_resolver.close_window`
   (`:121`), `terminal.process_kill` (`:121`), dan jalur mana pun yang menutup
   jendela. Menolak dengan pesan jujur, bukan diam.
2. **Buang `close_app`/`close_window` dari daftar yang boleh ditebak
   `_detect_action`** (`computer_settings.py:580`). Aksi destruktif tidak boleh
   jadi hasil "pick the closest action".
3. **Tool `close_app(app_name)` yang benar** — menerima nama, memakai
   `target_resolver`, dan dideklarasikan ke sesi Live. Tanpa ini model tidak
   punya cara benar untuk menutup aplikasi bernama, sehingga akan terus
   menebak.
4. **`close_app` masuk `_DANGEROUS_ACTIONS`** (`:571`), atau minimal
   `requires_confirmation` di lapis tool.
5. **`shutdown_jarvis` butuh konfirmasi** dan penggantian `os._exit(0)` dengan
   shutdown tertib.
6. **Longgarkan anchor** pola `close_target` agar toleran terhadap sapaan
   ("jarvis", "tolong", "hey").

### Efek samping yang saya khawatirkan

- Mengubah `_detect_action` mempengaruhi **semua** aksi `computer_settings`
  (~60 fungsi), bukan hanya close. Perlu tes regresi volume/brightness/wifi.
- Konfirmasi pada `shutdown_jarvis` mengubah perilaku yang mungkin sudah jadi
  kebiasaan Anda ("Jarvis, matikan" langsung mati). Itu keputusan Anda.
- `main.py` FROZEN. Perbaikan 3 dan 5 menyentuhnya.
- Penjaga proses-sendiri berpotensi menolak kasus sah (Anda memang ingin
  menutup jendela Jarvis lewat perintah). Perlu jalur eksplisit terpisah.

---

## MASALAH 1 — "buka app instagram" membuka browser

### VERDICT: **SEBAGIAN** — mekanismenya bukan yang dihipotesiskan

Hipotesis: jalur cepat mencocokkan "instagram" → `known_sites` → URL, dan kata
"app" diabaikan. **Diverifikasi dengan menjalankan router:**

| Kalimat | Hasil nyata |
|---|---|
| `buka instagram` | `OPEN_URL {url: https://www.instagram.com}` ← hipotesis **benar** |
| `buka app instagram` | `OPEN_APP {app: "app instagram"}` ← hipotesis **salah** |
| `buka aplikasi instagram` | `OPEN_APP {app: "aplikasi instagram"}` ← hipotesis **salah** |

Kata "app"/"aplikasi" **diperhatikan** — bukan diabaikan. Urutannya
(`router.py:220-233`): `key in known_sites` gagal karena kunci sebenarnya
adalah `"app instagram"`, lalu `len(key.split()) <= 3` → `OPEN_APP`.

### Lalu kenapa browser yang terbuka?

Dua mekanisme berbeda, tergantung lane.

**(1) Lane ketikan — Start Menu yang menyerah ke pencarian web.**
Slot membawa `"app instagram"` apa adanya. `_normalize`
(`actions/open_app.py:68-78`) mencocokkan substring: `"instagram" in "app instagram"`
→ mengembalikan alias `"Instagram"` (`open_app.py:57`). Lalu
`_launch_windows` (`open_app.py:80-116`) berurutan:

```
:82   shutil.which("Instagram")            → gagal (bukan di PATH)
:95   ":" in "Instagram"                   → tidak
:103  pyautogui: tekan Win, ketik nama, Enter
```

Baris 103-112 adalah **pencarian Start Menu buta**. Bila Windows tidak
menemukan aplikasi lokal bernama itu, menekan Enter membuka **hasil pencarian
web Bing di browser default**. Itulah browser yang Anda lihat. Fungsi ini tetap
`return True` (`:112`) — jadi Jarvis melaporkan "berhasil" padahal tidak.

Tidak ada registry aplikasi terpasang. Penemuannya hanya: tabel alias
hardcoded (`:14-66`), `shutil.which` (PATH), lalu tebakan Start Menu.

**(2) Lane suara — `known_sites` tidak pernah dikonsultasi.**
`main.py` tidak memakai `IntentRouter`. Model memilih antara `open_app`
(`main.py:127`) dan `browser_control` (`main.py:278`). Bagi model, Instagram
adalah situs web, jadi `browser_control` sering menang.

**(3) Bonus yang mengejutkan** — `open_app.py:57` memetakan Instagram di Linux
langsung ke `"firefox"`. Pemetaan aplikasi→browser memang ditulis di sana.

### Jawaban pertanyaan (e): nama cocok dua-duanya

`router.py:225-228` — `known_sites` **selalu menang**, dicek sebelum
`_APP_HINTS`. Tidak ada pertimbangan apakah aplikasinya benar-benar terpasang.

### Perbaikan minimal yang saya usulkan

1. **Buang kata penanda dari slot**: `"app instagram"` → `"instagram"`, dan
   jadikan kehadiran "app/aplikasi" sebagai **sinyal preferensi** yang
   mengalahkan `known_sites`.
2. **Ganti tebakan Start Menu dengan penemuan nyata** — pindai
   `%ProgramData%\Microsoft\Windows\Start Menu\Programs` dan `%APPDATA%\...`
   untuk `.lnk`. Kalau tidak ketemu, **katakan tidak ketemu**, jangan
   `return True`.
3. **Jangan pernah `return True` dari jalur yang tidak terverifikasi**
   (`open_app.py:112`) — laporan sukses palsu inilah yang membuat perilakunya
   membingungkan.

### Efek samping yang saya khawatirkan

- Membuang fallback Start Menu akan membuat beberapa aplikasi yang selama ini
  "berhasil" jadi gagal. Secara jujur itu memang sudah gagal, tapi terasa
  seperti regresi.
- Memprioritaskan aplikasi di atas `known_sites` mengubah "buka youtube" dari
  membuka situs menjadi mencari aplikasi.

---

## MASALAH 2 — Jarvis tidak pernah bertanya saat bingung

### VERDICT: **TERBUKTI**

**(a) & (b)** `clarify` ada dan kontraknya benar —
`jarvis/agent/tools/clarify.py:18` `name = "clarify"`, dengan penjaga
non-interaktif di `:35` (cron/headless tidak boleh bertanya, sesuai
`adapters/base.py:11`). Terdaftar sebagai grup di `toolgroups.py:53`.

**(c) TIDAK ADA di `TOOL_DECLARATIONS`.** `rg '"clarify"' main.py` → nol hasil.
Sesi Gemini Live melihat 21 tool, `clarify` bukan salah satunya.

**(d) Tidak ada instruksi bertanya balik di `core/prompt.txt`.** Pencarian
`ask|tanya|clarif|ambigu|unsure|confus` hanya menghasilkan positif palsu —
substring "ask" di dalam kata "task" (`prompt.txt:13,18,19,22`). Yang ada justru
kebalikannya, `prompt.txt` baris terakhir:

> `CRITICAL: Speak/Take action immediately based on available info. Assume and proceed.`

**"Assume and proceed"** — persona secara eksplisit menyuruh menebak, bukan
bertanya. Ini penyebab paling langsung dari keluhan Anda.

**(e)** Untuk lane suara, jalur cepat router tidak relevan (suara tidak lewat
`IntentRouter`), tapi hasilnya sama: `clarify` tidak ada di daftar tool,
sehingga **tidak mungkin terpanggil**. Di lane agent MK50 `clarify` tersedia
lewat auto-discovery dan bisa dipakai.

### Perbaikan minimal yang saya usulkan

1. Deklarasikan `clarify` ke sesi Live — bisa **tanpa menyentuh `main.py`**,
   lewat seam `voice_tasks.py`/`google_voice.py` yang sudah terbukti.
2. Tambahkan aturan ambiguitas di prompt sebagai **section baru** (mekanisme
   wrapper `_load_system_prompt` sudah ada), yang menyeimbangkan
   "Assume and proceed" — mis. tebak untuk hal yang mudah dibatalkan, tanya
   untuk hal yang destruktif atau tak-reversibel.

### Efek samping yang saya khawatirkan

- Terlalu banyak bertanya akan terasa lebih buruk daripada menebak. Aturannya
  harus sempit: hanya untuk aksi destruktif/ambigu-berbahaya.
- `prompt.txt` FROZEN dan milik Anda; kalimat "Assume and proceed" tampak
  disengaja. Menyeimbangkannya adalah keputusan Anda, bukan saya.

---

## MASALAH 4 — Percakapan terasa kaku, tanpa inisiatif

### VERDICT: **TERBUKTI, berlapis** — kelima lapisnya nyata

**(a) Composer mati, dan bahkan bila hidup ia tidak menambah inisiatif.**
`config.yaml`: `release_controls.naturalizer: false`,
`auxiliary.response_composer.enabled: false`. Docstring-nya
(`jarvis/agent/response_composer.py:1-6`) menjelaskan batasnya:

> *"The composer never owns a result: it only proposes a new `speech_text` for a
> verified `ConversationDelivery`."*

Jadi ia **hanya memparafrase ulang** kalimat yang sudah ditentukan
deterministik, dengan anchor faktual yang harus dipertahankan. Menyalakannya
membuat kalimat lebih luwes, **tidak** membuat Jarvis lebih berinisiatif.
Tidak ada komentar yang menjelaskan kenapa dimatikan; `config.yaml`
menandainya "opt-in; delivery Fase 3 tetap default aman".

**(b) ACK memang tiga kalimat tetap, dipilih acak.** Dikonfirmasi:
`jarvis/agent/interaction.py:9` `import random`, `:233` `pick = chooser or random.choice`,
membaca `agent.interaction.ack_templates.{lang}` (`:214`). Tiga kalimat per
bahasa di `config.yaml`. Variasinya kosmetik.

**(c) `core/prompt.txt` (2929 byte) tidak punya aturan gaya percakapan.**
Yang ada hanya routing tool dan satu aturan panjang (`prompt.txt:13`):

> `Length: Match response length to the task. Briefing = short. Complex analysis = thorough.`

**Tidak ada** aturan tentang: nada, kapan bertanya balik, kapan berinisiatif,
bagaimana menindaklanjuti. Ditutup dengan `Assume and proceed`.

**(d) ProactiveEngine punya SATU pemicu saja.** `actions/proactive.py:22`
`min_silence_secs: int = 900`, dan `:29-38`:

```python
return silence >= self.min_silence_secs and gap >= self.check_cooldown
```

Hanya durasi diam. Tidak ada sinyal lain — bukan CPU, bukan error di layar,
bukan cron yang akan jatuh tempo. Dan `boot.morning_briefing_enabled: false`
mematikan satu-satunya inisiatif terjadwal lain.

**(e) Awareness berbicara ke ruang kosong — dikonfirmasi.**
`jarvis/core/screen_awareness.py:221` dan `:244` mem-publish
`BUS.publish("awareness.context", model=model)`.

```
rg 'subscribe\("awareness'  →  NOL HASIL
```

**Tidak ada satu pun subscriber.** Menyalakan `awareness.enabled: true` hari ini
akan mengonsumsi CPU untuk menangkap layar, mengisi retensi 200 snapshot, dan
**hasilnya dibuang**. Modul ini butuh konsumen lebih dulu, bukan sekadar
di-toggle.

**(f) Rasio deterministik vs LLM — berbeda tajam per lane.**

| Lane | Jalur |
|---|---|
| Ketikan | `IntentRouter._rules` (regex) **lebih dulu**; LLM hanya dipanggil bila semua pola gagal (`router.py:157-159`). Untuk perintah umum (buka/tutup/volume/screenshot) jawaban **selalu** dari template. |
| Suara | Tidak pernah lewat `IntentRouter`; model yang memutuskan. |

Jadi kekakuan yang Anda rasakan **paling kuat di lane ketikan** — di sana
mayoritas ucapan memang ditangani regex + template, persis dugaan Anda. Di lane
suara penyebabnya berbeda: prompt yang minim aturan gaya, ACK template, dan
tidak adanya `clarify`.

### Perbaikan minimal yang saya usulkan

1. Tambahkan **section gaya percakapan** ke prompt lewat wrapper (nada, kapan
   menindaklanjuti, kapan menawarkan langkah berikutnya).
2. **Perluas pemicu proaktif** dari sekadar diam: CPU tinggi berkepanjangan,
   cron jatuh tempo, tugas latar selesai, jam kerja.
3. **Jangan nyalakan `awareness` sebelum ada konsumen.** Bangun subscriber
   dulu (mis. `ProactiveEngine` berlangganan `awareness.context`).
4. Composer boleh dinyalakan, tapi **jangan berharap ia menambah inisiatif** —
   itu pekerjaan prompt, bukan composer.

### Efek samping yang saya khawatirkan

- Menyalakan awareness tanpa denylist yang ditinjau = risiko privasi nyata.
- Pemicu proaktif yang terlalu agresif berubah cepat dari "hadir" jadi
  "mengganggu". Perlu batas frekuensi keras.

---

## MASALAH 5 — Tombol batal/kembali di Task Deck

### VERDICT: **SEBAGIAN** — batal tersambung penuh; "kembali" memang tidak pernah ada

**(a) Rantai batal lengkap dan tersambung.**

```
task_strip.py:32   cancel_requested = pyqtSignal(str)
task_strip.py:107  mousePressEvent → emit(task_id)          [hit-test rect ✕]
task_wiring.py:78  strip.cancel_requested.connect(_cancel)
task_wiring.py:88  dispatch.cancel_task(id) → fallback REGISTRY.cancel(id)
dispatch.py:128    cancel_task → TaskHandle.cancel()
dispatch.py:63     session.cancel() + REGISTRY.cancel(bg.id)
```

Deck juga: `task_deck.py:113` `cancel_requested`, disambung di
`task_wiring.py:74`. Jadi sinyalnya **sampai** ke registry.

**(b) Ketiga checkpoint terpasang.** `jarvis/agent/loop.py`:

| # | Lokasi | Kode |
|---|---|---|
| ① antar iterasi | `loop.py:172-173` | `if session.cancelled or _cancelled(bg_task):` |
| ② progres | `loop.py:180` | `_task_update(bg_task, iteration=…)` |
| ③ sebelum tiap tool | `loop.py:331-333` | `if _cancelled(bg_task): return ToolResult.fail(...)` |

**(c) ⚠️ Inilah penyebab paling mungkin dari "tidak berfungsi".**
`loop.py:171`:

```python
        resp = await asyncio.to_thread(cl.chat, messages, tool_schemas)
```

Pemeriksaan batal ada **sebelum** baris ini, bukan selama. Panggilan LLM adalah
I/O jaringan yang memblokir dengan `agent.request_timeout_s: 120`. Bila user
menekan ✕ tepat saat agent menunggu jawaban model, **tidak ada yang membaca
event batal sampai panggilan itu kembali** — bisa sampai 2 menit. Dari sisi
user: "tombolnya tidak berfungsi."

Hal yang sama berlaku untuk tool subprocess (`terminal`, `execute_code`) — ini
batas yang sudah saya catat di `toolgroups.py` saat Fase 1-2 dan **belum**
diperbaiki.

**(d) Tombol "kembali" tidak pernah dibuat.** Dikonfirmasi dua-duanya:

- `rg -i "kembali|back" jarvis/ui/task_deck.py task_strip.py` → tidak ada tombol
- `jarvis/ui/stage.py` **tidak punya konsep riwayat** — hanya `show`/`show_child`/
  `hide_all`/`activate`. Tidak ada `back()`, tidak ada tumpukan panel sebelumnya.

Jadi ini bukan bug; ini fitur yang belum ada. Saya tidak pernah membangunnya di
§8.5, dan spesifikasinya juga tidak memintanya.

### Perbaikan minimal yang saya usulkan

1. **Batal saat menunggu LLM** — bungkus panggilan `cl.chat` dengan
   `asyncio.wait_for` berdurasi pendek yang di-loop, atau jalankan dalam task
   yang bisa di-`cancel()`, sehingga event batal terbaca dalam <2 detik
   sesuai kriteria.
2. **Hard-kill subprocess** — `terminal`/`code_exec` beralih dari
   `subprocess.run` ke `Popen` + process group.
3. **Tombol kembali** — tambahkan `stage.back()` dengan satu slot "panel
   sebelumnya" (bukan tumpukan penuh), lalu tombolnya di Task Deck.

### Efek samping yang saya khawatirkan

- Membungkus `cl.chat` menyentuh jalur inti agent yang dipakai **semua** tugas,
  termasuk cron. Salah tangani = tugas normal ikut terpotong.
- `stage.back()` mengubah semantik ContentStage yang dipakai panel lain
  (vision/info/home) — perlu tes regresi `test_browser_routing_p0.py`.

---

## Ringkasan prioritas

| # | Masalah | Verdict | Tingkat |
|---|---|---|---|
| **3** | Menutup Jarvis sendiri | TERBUKTI + nol penjaga | 🔴 **keselamatan** |
| 2 | Tidak pernah bertanya | TERBUKTI | 🟠 |
| 5c | Batal tak terbaca saat menunggu LLM | TERBUKTI | 🟠 |
| 1 | Buka app → browser | SEBAGIAN (mekanisme berbeda) | 🟡 |
| 4 | Percakapan kaku | TERBUKTI berlapis | 🟡 |
| 5d | Tombol kembali | Fitur belum ada | 🟢 |

**Satu hal yang menurut saya paling mendesak**, dan paling murah: penjaga
proses-sendiri (3g). Saat ini tidak ada apa pun yang mencegah Jarvis
mengeksekusi perintah yang membunuh dirinya, di **tiga** jalur berbeda
(`close_app` Alt+F4, `shutdown_jarvis`, `psutil.terminate` tanpa cek PID).

---

*Diagnosis oleh Claude · 2026-07-27 · nol berkas kode diubah*

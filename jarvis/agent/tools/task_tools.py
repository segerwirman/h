"""Tool tugas latar (AUDIT_REPORT §8.4c) — task_start / status / cancel / result.

Didefinisikan SEKALI di sini lalu dipakai dua audiens:

* agent MK50 lewat auto-discovery registry;
* sesi Gemini Live lewat ``jarvis.integrations.voice_tasks`` yang menyuntik
  schema-nya dari registry ini — pola yang sama dengan ``google_voice``,
  sehingga ``main.py`` (FROZEN) tidak perlu disentuh.

Keempatnya **non-blocking**: hanya membaca/menulis registry di memori, jadi
aman dipanggil kapan saja tanpa mengganggu latensi suara.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.tasks import REGISTRY, TaskStatus

_MAX_RESULT_CHARS = 4000


def _fmt(view) -> str:
    bits = [f"[{view.id}] {view.title or view.prompt[:60]}",
            f"status={view.status.value}"]
    if view.status is TaskStatus.RUNNING:
        bits.append(f"progres={int(view.progress * 100)}%")
        if view.step:
            bits.append(f"langkah={view.step}")
    if view.status is TaskStatus.QUEUED:
        bits.append("menunggu giliran")
    if view.elapsed:
        bits.append(f"{view.elapsed:.0f}s")
    if view.error:
        bits.append(f"error={view.error[:160]}")
    return " · ".join(bits)


class _StartParams(BaseModel):
    task: str = Field(description="Perintah lengkap yang harus dikerjakan")
    # BUKAN "title": Tool.json_schema() memanggil _strip_titles() yang membuang
    # SETIAP kunci bernama "title" secara rekursif (base.py:91), sehingga
    # parameter dengan nama itu hilang diam-diam dari schema LLM.
    label: str = Field("", description="Judul singkat, layak diucapkan")


class TaskStart(Tool):
    name = "task_start"
    description = (
        "Mulai tugas latar panjang (riset, bangun proyek, otomasi browser). "
        "Kembali SEKETIKA dengan id. WAJIB dipakai untuk apa pun yang >5 detik. "
        "Jangan pernah bilang 'tunggu sebentar' lalu diam."
    )
    params_schema = _StartParams
    timeout_s = 15

    async def run(self, task: str = "", label: str = "", **_) -> ToolResult:
        text = str(task or "").strip()
        if not text:
            return ToolResult.fail("task kosong")
        from jarvis.agent import dispatch
        started = dispatch.dispatch_task(text, title=str(label or "").strip() or None)
        if started is None:
            # Bedakan sebabnya — "sedang sibuk" dan "belum dikonfigurasi"
            # menuntut respons berbeda dari model.
            if dispatch.is_active(text):
                return ToolResult.fail(
                    "tugas dengan perintah yang sama masih berjalan")
            if not dispatch.available():
                from jarvis.agent.interaction import unavailable_reason
                return ToolResult.fail(unavailable_reason(text))
            return ToolResult.fail(
                f"antrean penuh (maks {REGISTRY.queue_max} tugas aktif)")
        return ToolResult.success(
            {"id": started.id, "title": started.title,
             "status": started.status.value},
            display=f"tugas {started.id} dimulai")


class _IdParams(BaseModel):
    id: str = Field("", description="Id tugas, mis. T-a3f1")


class TaskStatusTool(Tool):
    name = "task_status"
    description = (
        "Daftar tugas yang sedang berjalan + progres. Pakai saat user bertanya "
        "'sudah sampai mana', 'masih lama?', 'lagi ngapain?'."
    )
    params_schema = _IdParams
    read_only = True
    timeout_s = 15

    async def run(self, id: str = "", **_) -> ToolResult:  # noqa: A002
        tid = str(id or "").strip()
        if tid:
            view = REGISTRY.get(tid)
            if view is None:
                return ToolResult.fail(f"tugas {tid} tidak ditemukan")
            return ToolResult.success(_fmt(view), display=f"status {tid}")
        active = REGISTRY.active()
        if not active:
            return ToolResult.success("Tidak ada tugas latar yang berjalan.",
                                      display="0 tugas aktif")
        lines = [_fmt(v) for v in
                 sorted(active, key=lambda v: v.created_at)]
        return ToolResult.success("\n".join(lines),
                                  display=f"{len(lines)} tugas aktif")


class TaskCancel(Tool):
    name = "task_cancel"
    description = "Batalkan tugas latar."
    params_schema = _IdParams
    timeout_s = 15

    async def run(self, id: str = "", **_) -> ToolResult:  # noqa: A002
        tid = str(id or "").strip()
        if not tid:
            return ToolResult.fail("butuh id tugas")
        view = REGISTRY.get(tid)
        if view is None:
            return ToolResult.fail(f"tugas {tid} tidak ditemukan")
        if not view.active:
            return ToolResult.fail(
                f"tugas {tid} sudah {view.status.value}, tidak bisa dibatalkan")
        # Batalkan lewat dispatch bila handle-nya masih ada, supaya
        # Session.cancelled ikut ter-set (loop lama membacanya).
        from jarvis.agent import dispatch
        if not dispatch.cancel_task(tid):
            REGISTRY.cancel(tid)
        return ToolResult.success(f"Tugas {tid} dibatalkan.",
                                  display=f"batal {tid}")


class TaskResult(Tool):
    name = "task_result"
    description = "Ambil hasil lengkap tugas yang selesai."
    params_schema = _IdParams
    read_only = True
    timeout_s = 15

    async def run(self, id: str = "", **_) -> ToolResult:  # noqa: A002
        tid = str(id or "").strip()
        if not tid:
            return ToolResult.fail("butuh id tugas")
        view = REGISTRY.get(tid)
        if view is None:
            return ToolResult.fail(f"tugas {tid} tidak ditemukan")
        if view.active:
            return ToolResult.success(
                f"Tugas {tid} belum selesai — {_fmt(view)}",
                display=f"{tid} belum selesai")
        if view.status is TaskStatus.FAILED:
            return ToolResult.fail(view.error or "tugas gagal tanpa keterangan")
        if view.status is TaskStatus.CANCELLED:
            return ToolResult.success(f"Tugas {tid} dibatalkan.",
                                      display=f"{tid} dibatalkan")
        return ToolResult.success(view.result[:_MAX_RESULT_CHARS] or "(kosong)",
                                  display=f"hasil {tid}")

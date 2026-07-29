"""Kontrak eksekusi untuk tugas agent yang perlu bukti keberhasilan.

Modul ini sengaja tidak mengeksekusi tool.  Ia menyiapkan task/policy yang
nantinya dapat dipasang tipis di seam dispatch, dan memvalidasi trace tool
tanpa mempercayai klaim akhir model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, quote_plus, urlparse


YOUTUBE_SORT_BY_DATE = "CAI%253D"
YOUTUBE_ALLOWED_TOOLS: tuple[str, ...] = (
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_back",
    "browser_dialog",
    "browser_media",
    "todo_write",
    "todo_read",
)

_PLAY_RE = re.compile(
    r"\b(?:putar(?:kan)?|puter(?:in)?|mainkan|play|tonton(?:kan)?|watch)\b",
    re.IGNORECASE,
)
_LATEST_RE = re.compile(
    r"\b(?:yang\s+)?(?:paling\s+baru|terbaru|terkini|latest|newest|most\s+recent)\b",
    re.IGNORECASE,
)
_YOUTUBE_RE = re.compile(r"\b(?:youtube|youtu\.be)\b", re.IGNORECASE)
_FROM_RE = re.compile(r"\b(?:dari|from|oleh|by)\s+(.+)$", re.IGNORECASE)
_EDGE_FILLER_RE = re.compile(
    r"^(?:(?:buka|open|dan|and|lalu|then|putar(?:kan)?|puter(?:in)?|"
    r"mainkan|play|tonton(?:kan)?|watch|video|channel|kanal|milik|punya|"
    r"dari|from|oleh|by|di|on|youtube)\s+)+|"
    r"(?:(?:video|channel|kanal|di|on|youtube|please|tolong)\s*)+$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ToolEvidence:
    """Satu observasi tool untuk validator kontrak.

    ``result`` boleh berupa dict, string hasil untuk LLM, atau ``ToolResult``.
    Bentuk longgar ini membuat validator tidak mengikat ulang loop/registry.
    """

    tool: str
    args: Mapping[str, Any] = field(default_factory=dict)
    result: Any = None
    ok: bool = True


@dataclass(frozen=True)
class ContractValidation:
    ok: bool
    errors: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        return "; ".join(self.errors)


@dataclass(frozen=True)
class YouTubeLatestPlayContract:
    original_task: str
    expected_channel: str
    search_query: str
    search_url: str
    allowed_tools: tuple[str, ...] = YOUTUBE_ALLOWED_TOOLS

    @property
    def execution_prompt(self) -> str:
        channel = self.expected_channel
        return (
            "[KONTRAK YOUTUBE_LATEST_PLAY]\n"
            f"Permintaan asli: {self.original_task}\n"
            f"Channel yang diharapkan: {channel}\n"
            f"URL pencarian WAJIB (sudah urut terbaru): {self.search_url}\n\n"
            "Ikuti urutan yang dapat dibuktikan ini:\n"
            "1. browser_navigate tepat ke URL pencarian wajib di atas.\n"
            "2. browser_snapshot; nilai hasil dan pilih video TERBARU milik "
            f"channel yang benar, yaitu {channel}.\n"
            "3. Gunakan hanya ref dari snapshot untuk browser_click atau "
            "browser_type. Selector CSS buta dilarang. Ambil snapshot baru "
            "sebelum SETIAP click/type dan setelah scroll/navigasi.\n"
            "   Jika consent/cookie berupa elemen DOM, snapshot lalu klik ref "
            "tombolnya; browser_dialog hanya untuk dialog JavaScript.\n"
            "4. Setelah membuka video, browser_snapshot lagi. Pastikan URL "
            "watch dan bukti youtube_watch menunjukkan video_id serta exact "
            "channel_name yang diharapkan. channel_id/channel_href watch juga "
            "harus sama dengan identitas channel pada hasil terpilih. Jangan "
            "memakai kemunculan nama channel pada body/rekomendasi sebagai "
            "bukti.\n"
            "5. browser_snapshot tepat sebelum browser_media(action='play'). "
            "Panggil play dengan expected_video_id dari youtube_watch, mis. "
            "browser_media(action='play', expected_video_id='<video_id>'). "
            "Gunakan action='status' bila hanya perlu membaca status.\n"
            "6. Nyatakan sukses hanya bila browser_media memverifikasi video "
            "ID halaman dan player sama dengan target, bukan iklan/pre-roll, "
            "tidak paused/tidak ended, dan currentTime benar-benar maju. Jika "
            "channel, kebaruan, atau playback tidak terbukti, laporkan gagal "
            "secara jujur; jangan menebak.\n"
            "Gunakan hanya tool yang diberikan untuk kontrak ini."
        )

    def validate(self, evidence: Iterable[ToolEvidence | Mapping[str, Any]]) \
            -> ContractValidation:
        return validate_youtube_latest_play(self, evidence)


@dataclass(frozen=True)
class PreparedAgentTask:
    original_task: str
    execution_prompt: str
    allowed_tools: tuple[str, ...] | None = None
    contract: YouTubeLatestPlayContract | None = None

    @property
    def contracted(self) -> bool:
        return self.contract is not None


def _clean_channel(value: str) -> str:
    value = _LATEST_RE.sub(" ", value)
    value = _YOUTUBE_RE.sub(" ", value)
    value = re.sub(r"[\s,.;:!?]+", " ", value).strip()
    previous = None
    while value and value != previous:
        previous = value
        value = _EDGE_FILLER_RE.sub("", value).strip()
    return value


def _extract_channel(task: str) -> str:
    # Bentuk paling eksplisit: "... terbaru dari <channel>" / "from <channel>".
    from_matches = list(_FROM_RE.finditer(task))
    if from_matches:
        channel = _clean_channel(from_matches[-1].group(1))
        if channel:
            return channel

    youtube = _YOUTUBE_RE.search(task)
    if youtube:
        channel = _clean_channel(task[youtube.end():])
        if channel:
            return channel

    # Bentuk terkait: "putar video terbaru Deddy Corbuzier di YouTube".
    stripped = _PLAY_RE.sub(" ", task)
    stripped = _LATEST_RE.sub(" ", stripped)
    stripped = _YOUTUBE_RE.sub(" ", stripped)
    return _clean_channel(stripped)


def detect_youtube_latest_play(task: str) \
        -> YouTubeLatestPlayContract | None:
    """Deteksi tugas play-video-YouTube-terbaru dan buat kontrak deterministik."""
    if not isinstance(task, str) or not task.strip():
        return None
    if not (_YOUTUBE_RE.search(task) and _PLAY_RE.search(task)
            and _LATEST_RE.search(task)):
        return None

    channel = _extract_channel(task)
    if not channel:
        return None
    # Kata generik saja bukan identitas channel yang bisa diverifikasi.
    if channel.casefold() in {"video", "channel", "kanal"}:
        return None

    query = f"{channel.casefold()} terbaru"
    search_url = (
        "https://www.youtube.com/results?search_query="
        f"{quote_plus(query)}&sp={YOUTUBE_SORT_BY_DATE}"
    )
    return YouTubeLatestPlayContract(
        original_task=task.strip(),
        expected_channel=channel,
        search_query=query,
        search_url=search_url,
    )


def prepare_task(task: str) -> PreparedAgentTask:
    """Siapkan prompt dan allowlist khusus bila task cocok dengan kontrak."""
    contract = detect_youtube_latest_play(task)
    if contract is None:
        return PreparedAgentTask(original_task=task, execution_prompt=task)
    return PreparedAgentTask(
        original_task=task,
        execution_prompt=contract.execution_prompt,
        allowed_tools=contract.allowed_tools,
        contract=contract,
    )


# Nama eksplisit agar seam pemanggil tidak perlu bergantung pada nama generik.
prepare_youtube_latest_play = prepare_task


def _coerce_evidence(item: ToolEvidence | Mapping[str, Any]) -> ToolEvidence:
    if isinstance(item, ToolEvidence):
        return item
    if not isinstance(item, Mapping):
        return ToolEvidence(
            tool=str(getattr(item, "tool", getattr(item, "name", ""))),
            args=getattr(item, "args", getattr(item, "arguments", {})) or {},
            result=getattr(item, "result", None),
            ok=bool(getattr(item, "ok", True)),
        )
    return ToolEvidence(
        tool=str(item.get("tool") or item.get("name") or ""),
        args=item.get("args") or item.get("arguments") or {},
        result=item.get("result", item.get("content")),
        ok=bool(item.get("ok", True)),
    )


def _result_content(result: Any) -> Any:
    if hasattr(result, "content"):
        return result.content
    return result


def _result_mapping(result: Any) -> Mapping[str, Any]:
    content = _result_content(result)
    if isinstance(content, Mapping):
        return content
    if hasattr(result, "meta") and isinstance(result.meta, Mapping):
        for key in ("snapshot", "media"):
            value = result.meta.get(key)
            if isinstance(value, Mapping):
                return value
    return {}


def _is_youtube_watch(value: str) -> bool:
    lowered = value.casefold()
    return ("youtube.com/watch" in lowered or "youtu.be/" in lowered)


def _evidence_ok(event: ToolEvidence) -> bool:
    result_ok = getattr(event.result, "ok", True)
    return bool(event.ok and result_ok)


def _channel_key(value: Any) -> str:
    value = str(value or "").casefold().lstrip("@").strip()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _ranked_youtube_results(snapshot: Mapping[str, Any]) \
        -> list[Mapping[str, Any]]:
    raw = snapshot.get("youtube_results", [])
    if not isinstance(raw, list):
        return []
    results = [item for item in raw if isinstance(item, Mapping)]

    def _rank(item: Mapping[str, Any]) -> int:
        try:
            return int(item.get("rank", 1_000_000))
        except (TypeError, ValueError):
            return 1_000_000

    return sorted(results, key=_rank)


def _youtube_video_id(value: Any) -> str:
    parsed = urlparse(str(value or ""))
    hostname = parsed.netloc.casefold().split(":", 1)[0]
    if hostname.endswith("youtu.be"):
        return parsed.path.strip("/").split("/", 1)[0]
    values = parse_qs(parsed.query).get("v", [])
    return str(values[0]).strip() if values else ""


def _channel_identities(value: Mapping[str, Any]) -> set[str]:
    identities: set[str] = set()
    channel_id = str(value.get("channel_id", "") or "").strip()
    if channel_id:
        identities.add("id:" + channel_id.casefold())
    href = str(value.get("channel_href", "") or "").strip()
    if href:
        path = urlparse(href).path.rstrip("/").casefold()
        if path:
            identities.add("path:" + path)
        match = re.search(r"/channel/([^/?#]+)", path, re.IGNORECASE)
        if match:
            identities.add("id:" + match.group(1).casefold())
    return identities


def _official_channel_result(
    results: Iterable[Mapping[str, Any]], channel_key: str,
) -> Mapping[str, Any] | None:
    """Prefer a verified exact-name result; reject ambiguous impersonators."""

    candidates = [
        item for item in results
        if _channel_key(item.get("channel")) == channel_key
    ]
    if not candidates:
        return None
    verified = [item for item in candidates if item.get("verified") is True]
    if verified:
        return verified[0]

    identities = [_channel_identities(item) for item in candidates]
    signatures = {frozenset(value) for value in identities if value}
    if all(identities) and len(signatures) == 1:
        return candidates[0]
    # Exact display names from different channel identities are ambiguous.
    return None


def validate_youtube_latest_play(
    contract: YouTubeLatestPlayContract,
    evidence: Iterable[ToolEvidence | Mapping[str, Any]],
) -> ContractValidation:
    """Validasi bukti, bukan narasi model, untuk keberhasilan playback."""
    events = [_coerce_evidence(item) for item in evidence]
    errors: list[str] = []

    navigations = [event for event in events
                   if event.tool == "browser_navigate"]
    if not navigations:
        errors.append("browser_navigate ke pencarian YouTube tidak ada")
    else:
        first_url = str(navigations[0].args.get("url", ""))
        if first_url != contract.search_url:
            errors.append("URL pencarian pertama bukan URL exact sort-by-date")
        if f"&sp={YOUTUBE_SORT_BY_DATE}" not in first_url:
            errors.append("URL pencarian tidak memuat sort-by-date")
        if not _evidence_ok(navigations[0]):
            errors.append("navigasi pencarian gagal")

    snapshot_ready = False
    on_sorted_search = False
    current_result_refs: set[str] = set()
    current_official_ref = ""
    current_official_result: Mapping[str, Any] | None = None
    selected_video_id = ""
    selected_channel_identities: set[str] = set()
    saw_structured_results = False
    saw_official_click = False
    saw_watch_channel_snapshot = False
    current_watch_channel_snapshot = False
    saw_verified_playback = False
    channel_key = _channel_key(contract.expected_channel)

    for event in events:
        tool = event.tool
        event_ok = _evidence_ok(event)

        if tool == "browser_navigate":
            url = str(event.args.get("url", ""))
            on_sorted_search = bool(event_ok and url == contract.search_url)
            snapshot_ready = False
            current_result_refs.clear()
            current_official_ref = ""
            current_official_result = None
            selected_video_id = ""
            selected_channel_identities.clear()
            current_watch_channel_snapshot = False
            saw_verified_playback = False
            continue

        if tool == "browser_snapshot":
            snapshot_ready = event_ok
            current_result_refs.clear()
            current_official_ref = ""
            current_official_result = None
            current_watch_channel_snapshot = False
            if event_ok:
                result_map = _result_mapping(event.result)
                url = str(result_map.get("url", ""))

                results = _ranked_youtube_results(result_map)
                if (on_sorted_search and url == contract.search_url
                        and results):
                    saw_structured_results = True
                    required = {"rank", "ref", "title", "channel", "age",
                                "href", "channel_id", "channel_href",
                                "verified"}
                    if any(not required.issubset(item) for item in results):
                        errors.append(
                            "youtube_results tidak memiliki field bukti lengkap")
                    current_result_refs = {
                        str(item.get("ref", "")).strip()
                        for item in results if str(item.get("ref", "")).strip()
                    }
                    official = _official_channel_result(results, channel_key)
                    if official is not None:
                        current_official_ref = str(
                            official.get("ref", "")).strip()
                        current_official_result = official

                watch = result_map.get("youtube_watch")
                if (saw_official_click and _is_youtube_watch(url)
                        and isinstance(watch, Mapping)):
                    watch_video_id = str(watch.get("video_id", "")).strip()
                    watch_channel = _channel_key(watch.get("channel_name"))
                    watch_title = str(watch.get("title", "")).strip()
                    channel_identity = str(
                        watch.get("channel_id")
                        or watch.get("channel_href") or "").strip()
                    watch_channel_identities = _channel_identities(watch)
                    if watch_channel != channel_key:
                        errors.append(
                            "youtube_watch channel_name tidak cocok exact "
                            "dengan channel target")
                    elif watch_video_id != selected_video_id:
                        errors.append(
                            "youtube_watch video_id tidak cocok dengan hasil "
                            "yang dipilih")
                    elif not watch_title or not channel_identity:
                        errors.append(
                            "youtube_watch tidak memiliki title/channel_id/href")
                    elif not (selected_channel_identities
                              & watch_channel_identities):
                        errors.append(
                            "youtube_watch channel_id/href tidak cocok dengan "
                            "hasil terpilih")
                    else:
                        saw_watch_channel_snapshot = True
                        current_watch_channel_snapshot = True
            continue

        if tool in {"browser_click", "browser_type"}:
            ref = str(event.args.get("ref", "")).strip()
            selector = str(event.args.get("selector", "")).strip()
            if not snapshot_ready:
                errors.append(f"{tool} tanpa snapshot baru sebelumnya")
            if not ref:
                errors.append(f"{tool} tidak memakai ref snapshot")
            if selector:
                errors.append(f"{tool} memakai selector buta")

            if tool == "browser_click" and ref in current_result_refs:
                if not current_official_ref:
                    errors.append(
                        "hasil terurut tidak memuat channel official yang benar")
                elif ref != current_official_ref:
                    errors.append(
                        "browser_click tidak memilih video official pertama "
                        "pada hasil terurut")
                elif not event_ok:
                    errors.append("browser_click video official gagal")
                else:
                    selected_video_id = _youtube_video_id(
                        (current_official_result or {}).get("href"))
                    selected_channel_identities = _channel_identities(
                        current_official_result or {})
                    if not selected_video_id:
                        errors.append(
                            "hasil official terpilih tidak memiliki video ID")
                    elif not selected_channel_identities:
                        errors.append(
                            "hasil official terpilih tidak memiliki "
                            "channel_id/href")
                    else:
                        saw_official_click = True
                        on_sorted_search = False
            snapshot_ready = False
            current_result_refs.clear()
            current_official_ref = ""
            current_official_result = None
            current_watch_channel_snapshot = False
            saw_verified_playback = False
            continue

        if tool == "browser_media" and str(
                event.args.get("action", "status")).casefold() == "play":
            if not snapshot_ready:
                errors.append("browser_media play tanpa snapshot baru")
            snapshot_ready = False
            state = _result_mapping(event.result)
            expected_video_id = str(
                event.args.get("expected_video_id", "")).strip()
            try:
                ready_state = int(state.get("readyState", 0))
                current_time = float(state.get("currentTime", 0.0))
            except (TypeError, ValueError):
                ready_state, current_time = 0, 0.0
            verified = (
                event_ok
                and current_watch_channel_snapshot
                and expected_video_id == selected_video_id
                and state.get("targetVideoId") == selected_video_id
                and state.get("pageVideoId") == selected_video_id
                and state.get("playerVideoId") == selected_video_id
                and state.get("targetMatched") is True
                and state.get("isAd") is False
                and bool(state.get("found"))
                and state.get("paused") is False
                and state.get("ended") is False
                and ready_state >= 2
                and current_time >= 0.0
                and bool(state.get("timeAdvanced"))
                and bool(state.get("playing"))
            )
            if expected_video_id != selected_video_id:
                errors.append(
                    "browser_media expected_video_id tidak cocok dengan video "
                    "terpilih")
            if state.get("isAd") is not False:
                errors.append("browser_media masih pada iklan/pre-roll")
            if state.get("pageVideoId") != selected_video_id:
                errors.append("browser_media pageVideoId tidak cocok target")
            if state.get("playerVideoId") != selected_video_id:
                errors.append("browser_media playerVideoId tidak cocok target")
            saw_verified_playback = saw_verified_playback or verified
            current_watch_channel_snapshot = False
            continue

        if tool == "browser_media":
            state = _result_mapping(event.result)
            if saw_verified_playback and event_ok and state.get("found"):
                saw_verified_playback = bool(
                    state.get("playing")
                    and state.get("isAd") is False
                    and state.get("pageVideoId") == selected_video_id
                    and state.get("playerVideoId") == selected_video_id)
            continue

        # Perubahan page/viewport membuat ref lama tidak lagi terpercaya.
        if tool in {"browser_navigate", "browser_back", "browser_scroll",
                    "browser_press"}:
            snapshot_ready = False
            current_result_refs.clear()
            current_official_ref = ""
            current_official_result = None
            current_watch_channel_snapshot = False
            saw_verified_playback = False

    if not saw_structured_results:
        errors.append("snapshot pencarian tidak memuat youtube_results terstruktur")
    if not saw_official_click:
        errors.append("video official terbaru belum diklik dengan sukses")
    if not saw_watch_channel_snapshot:
        errors.append("snapshot watch-page tidak membuktikan channel yang benar")
    if not saw_verified_playback:
        errors.append("media playing dan currentTime maju belum terverifikasi")

    # Hilangkan duplikasi tanpa mengubah urutan diagnosis.
    return ContractValidation(ok=not errors,
                              errors=tuple(dict.fromkeys(errors)))

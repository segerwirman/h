"""Phase 23 RED — bounded per-scene duration policy, cumulative SRT timing."""
from __future__ import annotations


def test_admit_duration_accepts_only_finite_bounded_int():
    from jarvis.core.content_timing_policy import admit_duration

    assert admit_duration(5)["ok"] is True
    assert admit_duration(1)["ok"] is True
    assert admit_duration(600)["ok"] is True
    assert admit_duration(True)["ok"] is False          # bool reject
    assert admit_duration(5.0)["ok"] is False           # float reject
    assert admit_duration("5")["ok"] is False
    assert admit_duration(0)["ok"] is False
    assert admit_duration(-3)["ok"] is False
    assert admit_duration(601)["ok"] is False
    assert admit_duration(float("nan"))["ok"] is False
    assert admit_duration(float("inf"))["ok"] is False


def test_admit_durations_validates_each_and_total_cap():
    from jarvis.core.content_timing_policy import admit_durations

    ok = admit_durations([5, 10, 15])
    assert ok["ok"] is True
    assert ok["durations"] == [5, 10, 15]

    assert admit_durations([5, -1, 15])["ok"] is False
    assert admit_durations([5, "x"])["ok"] is False
    assert admit_durations([5, 0])["ok"] is False
    # total cap: 3600 detik (via kombinasi; durasi tunggal cap 600)
    assert admit_durations([600, 600, 600, 600, 600, 600])["ok"] is True
    assert admit_durations([600, 600, 600, 600, 600, 601])["ok"] is False
    assert admit_durations([3600])["ok"] is False       # melebihi cap durasi tunggal


def test_cumulative_timings_are_exact_and_monotonic():
    from jarvis.core.content_timing_policy import cumulative_timings

    assert cumulative_timings([5, 10, 15]) == [(0, 5), (5, 15), (15, 30)]
    assert cumulative_timings([1]) == [(0, 1)]
    assert cumulative_timings([]) == []


def test_srt_timestamp_is_standard_hh_mm_ss_mmm():
    from jarvis.core.content_timing_policy import srt_timestamp

    assert srt_timestamp(0) == "00:00:00,000"
    assert srt_timestamp(5) == "00:00:05,000"
    assert srt_timestamp(65) == "00:01:05,000"
    assert srt_timestamp(3661) == "01:01:01,000"


def test_build_srt_is_cumulative_and_validates_text_count():
    from jarvis.core.content_timing_policy import build_srt

    result = build_srt([5, 10], ["Narasi satu.", "Narasi dua."])
    assert result["ok"] is True
    content = result["content"]
    assert "00:00:00,000 --> 00:00:05,000" in content
    assert "00:00:05,000 --> 00:00:15,000" in content
    assert content.index("Narasi satu.") < content.index("Narasi dua.")

    assert build_srt([5, 10], ["Hanya satu teks."])["ok"] is False
    assert build_srt([], [])["ok"] is True


def test_default_durations_are_bounded_and_repeatable():
    from jarvis.core.content_timing_policy import default_durations

    assert default_durations(3) == [5, 5, 5]
    assert default_durations(0) == []

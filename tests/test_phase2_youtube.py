from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.agent.base import ToolResult
from jarvis.agent.task_contracts import (
    ToolEvidence,
    YOUTUBE_ALLOWED_TOOLS,
    detect_youtube_latest_play,
    prepare_task,
)
from jarvis.agent.tools import browser


EXACT_TASK = "buka dan putar youtube deddy corbuzier terbaru"
EXACT_URL = (
    "https://www.youtube.com/results?"
    "search_query=deddy+corbuzier+terbaru&sp=CAI%253D"
)


def test_detect_exact_youtube_latest_play_and_sorted_url():
    contract = detect_youtube_latest_play(EXACT_TASK)

    assert contract is not None
    assert contract.expected_channel.casefold() == "deddy corbuzier"
    assert contract.search_url == EXACT_URL
    assert contract.search_query == "deddy corbuzier terbaru"


@pytest.mark.parametrize("task, channel", [
    ("putar video YouTube terbaru dari Deddy Corbuzier",
     "Deddy Corbuzier"),
    ("Please play the latest YouTube video from Kurzgesagt",
     "Kurzgesagt"),
    ("tonton video terbaru Najwa Shihab di YouTube", "Najwa Shihab"),
])
def test_detect_related_latest_play_tasks(task, channel):
    contract = detect_youtube_latest_play(task)

    assert contract is not None
    assert contract.expected_channel == channel
    assert contract.search_url.endswith("&sp=CAI%253D")


@pytest.mark.parametrize("task", [
    "buka YouTube Deddy Corbuzier",
    "video terbaru Deddy Corbuzier",
    "putar Spotify terbaru Deddy Corbuzier",
    "apa video YouTube terbaru?",
])
def test_non_matching_task_does_not_receive_youtube_contract(task):
    assert detect_youtube_latest_play(task) is None


def test_prepared_task_has_exact_prompt_and_real_tool_restriction():
    prepared = prepare_task(EXACT_TASK)

    assert prepared.contracted
    assert prepared.allowed_tools == YOUTUBE_ALLOWED_TOOLS
    assert EXACT_URL in prepared.execution_prompt
    assert "deddy corbuzier" in prepared.execution_prompt.casefold()
    assert "snapshot" in prepared.execution_prompt.casefold()
    assert "currentTime" in prepared.execution_prompt
    assert "todo_write" in prepared.allowed_tools
    assert "browser_media" in prepared.allowed_tools
    assert not ({
        "open_app",
        "youtube_video",
        "computer_type",
        "computer_click",
        "computer_key",
        "terminal",
        "browser_console",
        "browser_cdp",
        "browser_press",
    } & set(prepared.allowed_tools))


def test_unrelated_task_is_unchanged_and_unrestricted():
    prepared = prepare_task("jelaskan fotosintesis")

    assert not prepared.contracted
    assert prepared.execution_prompt == "jelaskan fotosintesis"
    assert prepared.allowed_tools is None


def _snapshot(url: str, text: str, refs=("j1",),
              youtube_results=None, youtube_watch=None) -> dict:
    return {
        "url": url,
        "title": "YouTube",
        "text": text,
        "elements": [
            {"ref": ref, "tag": "a", "type": "", "text": text,
             "href": "/watch?v=abc"}
            for ref in refs
        ],
        "youtube_results": list(youtube_results or []),
        "youtube_watch": youtube_watch,
    }


def _youtube_results_fixture():
    # Urutan server sudah newest-first. Hasil rank 1 memang lebih baru, tetapi
    # unofficial; official terbaru adalah rank 2, bukan official lama rank 3.
    return [
        {
            "rank": 1,
            "ref": "j1",
            "title": "Klip baru dari akun peniru",
            "channel": "Deddy Corbuzier",
            "channel_id": "UC-Fan-Clips",
            "channel_href": "https://www.youtube.com/channel/UC-Fan-Clips",
            "verified": False,
            "age": "1 jam yang lalu",
            "href": "https://www.youtube.com/watch?v=unofficial",
        },
        {
            "rank": 2,
            "ref": "j2",
            "title": "Episode official terbaru",
            "channel": "Deddy Corbuzier",
            "channel_id": "UC-Deddy-Official",
            "channel_href": (
                "https://www.youtube.com/channel/UC-Deddy-Official"),
            "verified": True,
            "age": "2 jam yang lalu",
            "href": "https://www.youtube.com/watch?v=official-new",
        },
        {
            "rank": 3,
            "ref": "j3",
            "title": "Episode official lama",
            "channel": "Deddy Corbuzier",
            "channel_id": "UC-Deddy-Official",
            "channel_href": (
                "https://www.youtube.com/channel/UC-Deddy-Official"),
            "verified": True,
            "age": "2 hari yang lalu",
            "href": "https://www.youtube.com/watch?v=official-old",
        },
    ]


def test_host_requires_fresh_known_ref_and_rejects_blind_selector():
    host = browser._BrowserHost()

    with pytest.raises(RuntimeError, match="browser_snapshot"):
        host.consume_snapshot("browser_click", "j1")

    host.record_snapshot(_snapshot("https://youtube.test/results", "result"))
    with pytest.raises(ValueError, match="selector CSS buta"):
        host.consume_snapshot("browser_click", "j1", "#video")

    host.record_snapshot(_snapshot("https://youtube.test/results", "result"))
    with pytest.raises(ValueError, match="tidak ada pada snapshot"):
        host.consume_snapshot("browser_click", "j99")

    host.record_snapshot(_snapshot("https://youtube.test/results", "result"))
    host.consume_snapshot("browser_click", "j1")
    with pytest.raises(RuntimeError, match="browser_snapshot"):
        host.consume_snapshot("browser_type", "j1")


def test_snapshot_ref_cannot_cross_session_owner():
    host = browser._BrowserHost()
    snap = _snapshot("https://youtube.test/results", "result")
    host.record_snapshot(snap, owner="session-a")

    with pytest.raises(RuntimeError, match="milik sesi lain"):
        host.consume_snapshot("browser_click", "j1", owner="session-b")
    with pytest.raises(RuntimeError, match="milik sesi lain"):
        host.consume_snapshot_for_media_play(owner="session-b")

    # Penolakan task lain tidak menghabiskan ref milik task asal.
    host.consume_snapshot("browser_click", "j1", owner="session-a")


class _FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def click(self, timeout):
        self.page.actions.append(("click", self.selector, timeout))
        self.page.url = "https://www.youtube.com/watch?v=abc"

    def fill(self, text, timeout):
        self.page.actions.append(("fill", self.selector, text, timeout))

    def press(self, key):
        self.page.actions.append(("press", key))


class _FakePage:
    def __init__(self, snapshots=None, media_states=None):
        self.url = "https://www.youtube.com/results"
        self.actions = []
        self.snapshots = list(snapshots or [])
        self.media_states = list(media_states or [])
        self.play_result = True

    def title(self):
        return "Fake YouTube"

    def evaluate(self, script):
        if script == browser._SNAPSHOT_JS:
            return self.snapshots.pop(0)
        if script == browser._MEDIA_STATE_JS:
            if len(self.media_states) > 1:
                return self.media_states.pop(0)
            return dict(self.media_states[0])
        if script == browser._MEDIA_PLAY_JS:
            self.actions.append(("media_play",))
            return self.play_result
        raise AssertionError("script tak dikenal pada fake page")

    def locator(self, selector):
        return _FakeLocator(self, selector)

    def wait_for_load_state(self, *args, **kwargs):
        self.actions.append(("wait_for_load_state", args, kwargs))

    def wait_for_timeout(self, milliseconds):
        self.actions.append(("wait_for_timeout", milliseconds))

    def goto(self, url, **kwargs):
        self.url = url
        self.actions.append(("goto", url, kwargs))


class _DirectHost(browser._BrowserHost):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.pages_seen = []

    def call(self, fn, timeout=60):
        self.pages_seen.append(self.page)
        return fn(self.page)


def _install_host(monkeypatch, page):
    host = _DirectHost(page)
    monkeypatch.setattr(
        browser._BrowserHost, "get", classmethod(lambda cls: host))
    return host


def test_browser_tools_share_page_and_snapshot_is_consumed(monkeypatch):
    page = _FakePage(snapshots=[
        _snapshot("https://www.youtube.com/results", "Deddy Corbuzier"),
    ])
    host = _install_host(monkeypatch, page)

    snap_result = asyncio.run(browser.BrowserSnapshot().run())
    click_result = asyncio.run(browser.BrowserClick().run(ref="j1"))

    assert snap_result.ok and click_result.ok
    assert snap_result.meta["snapshot"]["url"].endswith("/results")
    assert len({id(seen) for seen in host.pages_seen}) == 1
    assert page.actions[0][0] == "click"
    with pytest.raises(RuntimeError, match="browser_snapshot"):
        asyncio.run(browser.BrowserClick().run(ref="j1"))


def test_browser_snapshot_returns_structured_youtube_results_in_meta(
        monkeypatch):
    results = _youtube_results_fixture()
    page = _FakePage(snapshots=[
        _snapshot(EXACT_URL, "hasil", refs=("j1", "j2", "j3"),
                  youtube_results=results),
    ])
    _install_host(monkeypatch, page)

    result = asyncio.run(browser.BrowserSnapshot().run())

    assert result.ok
    assert result.meta["snapshot"]["youtube_results"] == results
    assert "#2 [j2] Episode official terbaru" in result.content
    assert "channel=Deddy Corbuzier" in result.content


def test_browser_snapshot_returns_structured_watch_identity(monkeypatch):
    watch = {
        "video_id": "official-new",
        "channel_name": "Deddy Corbuzier",
        "channel_id": "UC-Deddy-Official",
        "channel_href": "https://www.youtube.com/channel/UC-Deddy-Official",
        "title": "Episode official terbaru",
    }
    page = _FakePage(snapshots=[
        _snapshot("https://www.youtube.com/watch?v=official-new", "body",
                  youtube_watch=watch),
    ])
    _install_host(monkeypatch, page)

    result = asyncio.run(browser.BrowserSnapshot().run())

    assert result.meta["snapshot"]["youtube_watch"] == watch
    assert "video_id=official-new" in result.content
    assert "channel_id=UC-Deddy-Official" in result.content


def test_click_and_type_schema_do_not_advertise_selector():
    click_schema = browser.BrowserClick().json_schema()
    type_schema = browser.BrowserType().json_schema()
    click_properties = click_schema["properties"]
    type_properties = type_schema["properties"]

    assert "ref" in click_properties and "selector" not in click_properties
    assert "ref" in type_properties and "selector" not in type_properties
    assert "ref" in click_schema["required"]
    assert "ref" in type_schema["required"]


def test_context_guard_is_enabled_for_every_ref_or_media_tool():
    assert browser.BrowserSnapshot.wants_context is True
    assert browser.BrowserClick.wants_context is True
    assert browser.BrowserType.wants_context is True
    assert browser.BrowserMedia.wants_context is True


def test_tool_level_owner_guard_rejects_other_session(monkeypatch):
    page = _FakePage(snapshots=[
        _snapshot("https://www.youtube.com/results", "Deddy Corbuzier"),
    ])
    _install_host(monkeypatch, page)
    owner = SimpleNamespace(id="session-a")
    intruder = SimpleNamespace(id="session-b")

    asyncio.run(browser.BrowserSnapshot().run(_session=owner))

    with pytest.raises(RuntimeError, match="milik sesi lain"):
        asyncio.run(browser.BrowserClick().run(ref="j1", _session=intruder))
    result = asyncio.run(
        browser.BrowserClick().run(ref="j1", _session=owner))
    assert result.ok


def test_navigate_invalidates_old_snapshot(monkeypatch):
    page = _FakePage()
    host = _install_host(monkeypatch, page)
    host.record_snapshot(_snapshot(page.url, "old"))

    result = asyncio.run(browser.BrowserNavigate().run(EXACT_URL))

    assert result.ok
    with pytest.raises(RuntimeError, match="browser_snapshot"):
        host.consume_snapshot("browser_click", "j1")


def _media(found=True, paused=False, ended=False, ready=4, current=0.0,
           page_video_id="abc", player_video_id="abc", is_ad=False):
    return {
        "found": found,
        "paused": paused,
        "ended": ended,
        "readyState": ready,
        "currentTime": current,
        "pageVideoId": page_video_id,
        "playerVideoId": player_video_id,
        "playerTitle": "Target video",
        "playerAuthor": "Deddy Corbuzier",
        "isAd": is_ad,
    }


def test_browser_media_play_verifies_real_state_and_time_advance(monkeypatch):
    page = _FakePage(media_states=[
        _media(paused=True, current=10.0),
        _media(paused=False, current=10.9),
    ])
    page.url = "https://www.youtube.com/watch?v=abc"
    host = _install_host(monkeypatch, page)
    host.record_snapshot(_snapshot(page.url, "Deddy Corbuzier"))

    result = asyncio.run(browser.BrowserMedia().run(
        action="play", expected_video_id="abc"))

    assert result.ok
    assert result.content["url"] == page.url
    assert result.content["title"] == "Fake YouTube"
    assert result.content["paused"] is False
    assert result.content["ended"] is False
    assert result.content["readyState"] == 4
    assert result.content["currentTime"] == 10.9
    assert result.content["timeAdvanced"] is True
    assert result.content["playing"] is True
    assert result.content["targetVideoId"] == "abc"
    assert result.content["targetMatched"] is True
    assert result.content["isAd"] is False


def test_browser_media_degrades_honestly_when_time_does_not_advance(
        monkeypatch):
    page = _FakePage(media_states=[
        _media(paused=True, current=10.0),
        _media(paused=False, current=10.0),
    ])
    host = _install_host(monkeypatch, page)
    host.record_snapshot(_snapshot(page.url, "Deddy Corbuzier"))

    result = asyncio.run(browser.BrowserMedia().run(
        action="play", expected_video_id="abc"))

    assert not result.ok
    assert "tidak terverifikasi" in result.error
    assert result.content["url"] == page.url
    assert result.content["paused"] is False
    assert result.content["currentTime"] == 10.0
    assert result.meta["media"]["timeAdvanced"] is False
    assert result.meta["media"]["playing"] is False


@pytest.mark.parametrize("state, error_text", [
    (_media(player_video_id="different"), "data player tidak cocok"),
    (_media(player_video_id="ad-video", is_ad=True), "iklan/pre-roll"),
])
def test_browser_media_rejects_player_mismatch_and_preroll(
        monkeypatch, state, error_text):
    page = _FakePage(media_states=[state])
    page.url = "https://www.youtube.com/watch?v=abc"
    host = _install_host(monkeypatch, page)
    host.record_snapshot(_snapshot(page.url, "Deddy Corbuzier"))

    result = asyncio.run(browser.BrowserMedia().run(
        action="play", expected_video_id="abc"))

    assert not result.ok
    assert error_text in result.error
    assert not any(action[0] == "media_play" for action in page.actions)


def test_browser_media_play_can_control_current_video_without_target_id(monkeypatch):
    page = _FakePage(media_states=[
        _media(paused=True, current=10.0),
        _media(paused=False, current=10.9),
    ])
    host = _install_host(monkeypatch, page)
    host.record_snapshot(_snapshot(page.url, "Deddy Corbuzier"))

    result = asyncio.run(browser.BrowserMedia().run(action="play"))

    assert result.ok
    assert result.content["playing"] is True
    assert result.content["targetVideoId"] == ""


def _valid_evidence(contract):
    results = _youtube_results_fixture()
    return [
        ToolEvidence("browser_navigate", {"url": contract.search_url},
                     "terbuka", True),
        ToolEvidence("browser_snapshot", {}, {
            "url": contract.search_url,
            "text": "Hasil terbaru Deddy Corbuzier",
            "youtube_results": results,
        }, True),
        ToolEvidence("browser_click", {"ref": "j2"}, "diklik", True),
        ToolEvidence("browser_snapshot", {}, {
            "url": "https://www.youtube.com/watch?v=official-new",
            "title": "Episode baru - Deddy Corbuzier",
            "text": "Deddy Corbuzier official channel",
            "youtube_watch": {
                "video_id": "official-new",
                "channel_name": "Deddy Corbuzier",
                "channel_id": "UC-Deddy-Official",
                "channel_href": (
                    "https://www.youtube.com/channel/UC-Deddy-Official"),
                "title": "Episode official terbaru",
            },
        }, True),
        ToolEvidence("browser_media", {
            "action": "play", "expected_video_id": "official-new",
        }, {
            "found": True,
            "url": "https://www.youtube.com/watch?v=official-new",
            "paused": False,
            "ended": False,
            "readyState": 4,
            "currentTime": 2.1,
            "timeAdvanced": True,
            "playing": True,
            "targetVideoId": "official-new",
            "pageVideoId": "official-new",
            "playerVideoId": "official-new",
            "targetMatched": True,
            "isAd": False,
        }, True),
    ]


def test_contract_validator_accepts_complete_evidence_only():
    contract = detect_youtube_latest_play(EXACT_TASK)

    validation = contract.validate(_valid_evidence(contract))

    assert validation.ok, validation.reason


def test_body_channel_mention_cannot_fake_structured_watch_identity():
    contract = detect_youtube_latest_play(EXACT_TASK)
    evidence = _valid_evidence(contract)
    watch = dict(evidence[3].result)
    watch["text"] = (
        "Deddy Corbuzier Deddy Corbuzier recommended videos and comments")
    watch["youtube_watch"] = {
        **watch["youtube_watch"],
        "channel_name": "Channel Tidak Resmi",
    }
    evidence[3] = ToolEvidence("browser_snapshot", {}, watch, True)

    validation = contract.validate(evidence)

    assert not validation.ok
    assert "channel_name tidak cocok exact" in validation.reason


def test_watch_video_id_must_match_selected_search_result():
    contract = detect_youtube_latest_play(EXACT_TASK)
    evidence = _valid_evidence(contract)
    watch = dict(evidence[3].result)
    watch["youtube_watch"] = {
        **watch["youtube_watch"], "video_id": "different-video",
    }
    evidence[3] = ToolEvidence("browser_snapshot", {}, watch, True)

    validation = contract.validate(evidence)

    assert not validation.ok
    assert "video_id tidak cocok" in validation.reason


def test_watch_channel_identity_must_match_selected_result():
    contract = detect_youtube_latest_play(EXACT_TASK)
    evidence = _valid_evidence(contract)
    watch = dict(evidence[3].result)
    watch["youtube_watch"] = {
        **watch["youtube_watch"],
        "channel_id": "UC-Impostor",
        "channel_href": "https://www.youtube.com/channel/UC-Impostor",
    }
    evidence[3] = ToolEvidence("browser_snapshot", {}, watch, True)

    validation = contract.validate(evidence)

    assert not validation.ok
    assert "channel_id/href tidak cocok" in validation.reason


def test_watch_recommendations_cannot_replace_selected_latest_video():
    contract = detect_youtube_latest_play(EXACT_TASK)
    evidence = _valid_evidence(contract)
    watch = dict(evidence[3].result)
    watch["youtube_results"] = [{
        "rank": 1,
        "ref": "j50",
        "title": "Episode lama yang direkomendasikan",
        "channel": "Deddy Corbuzier",
        "channel_id": "UC-Deddy-Official",
        "channel_href": (
            "https://www.youtube.com/channel/UC-Deddy-Official"),
        "verified": True,
        "age": "3 tahun yang lalu",
        "href": "https://www.youtube.com/watch?v=official-old",
    }]
    old_watch = {
        "url": "https://www.youtube.com/watch?v=official-old",
        "title": "Episode lama",
        "text": "Deddy Corbuzier",
        "youtube_watch": {
            **watch["youtube_watch"],
            "video_id": "official-old",
            "title": "Episode lama",
        },
    }
    old_media = {
        **evidence[4].result,
        "url": old_watch["url"],
        "targetVideoId": "official-old",
        "pageVideoId": "official-old",
        "playerVideoId": "official-old",
    }
    evidence = evidence[:3] + [
        ToolEvidence("browser_snapshot", {}, watch, True),
        ToolEvidence("browser_click", {"ref": "j50"}, "diklik", True),
        ToolEvidence("browser_snapshot", {}, old_watch, True),
        ToolEvidence("browser_media", {
            "action": "play", "expected_video_id": "official-old",
        }, old_media, True),
    ]

    validation = contract.validate(evidence)

    assert not validation.ok
    assert "video_id tidak cocok" in validation.reason


@pytest.mark.parametrize("changes, error_text", [
    ({"playerVideoId": "different-video", "targetMatched": False},
     "playerVideoId tidak cocok"),
    ({"playerVideoId": "ad-video", "targetMatched": False, "isAd": True},
     "iklan/pre-roll"),
])
def test_validator_rejects_player_mismatch_and_ad_state(changes, error_text):
    contract = detect_youtube_latest_play(EXACT_TASK)
    evidence = _valid_evidence(contract)
    media = {**evidence[4].result, **changes}
    evidence[4] = ToolEvidence(evidence[4].tool, evidence[4].args, media, True)

    validation = contract.validate(evidence)

    assert not validation.ok
    assert error_text in validation.reason


@pytest.mark.parametrize("wrong_ref", ["j1", "j3"])
def test_contract_validator_rejects_unofficial_or_older_official(wrong_ref):
    contract = detect_youtube_latest_play(EXACT_TASK)
    evidence = _valid_evidence(contract)
    evidence[2] = ToolEvidence(
        "browser_click", {"ref": wrong_ref}, "diklik", True)

    validation = contract.validate(evidence)

    assert not validation.ok
    assert "official pertama" in validation.reason
    assert "belum diklik dengan sukses" in validation.reason


def test_contract_validator_requires_successful_official_click():
    contract = detect_youtube_latest_play(EXACT_TASK)
    evidence = _valid_evidence(contract)
    evidence[2] = ToolEvidence(
        "browser_click", {"ref": "j2"},
        ToolResult.fail("click timeout"), True)

    validation = contract.validate(evidence)

    assert not validation.ok
    assert "video official gagal" in validation.reason


def test_validator_reads_real_toolresult_snapshot_meta():
    contract = detect_youtube_latest_play(EXACT_TASK)
    search_snapshot = {
        "url": contract.search_url,
        "text": "Hasil terurut",
        "youtube_results": _youtube_results_fixture(),
    }
    watch_snapshot = {
        "url": "https://www.youtube.com/watch?v=official-new",
        "title": "Episode official terbaru",
        "text": "Deddy Corbuzier official channel",
        "youtube_results": [],
        "youtube_watch": {
            "video_id": "official-new",
            "channel_name": "Deddy Corbuzier",
            "channel_id": "UC-Deddy-Official",
            "channel_href": (
                "https://www.youtube.com/channel/UC-Deddy-Official"),
            "title": "Episode official terbaru",
        },
    }
    evidence = [
        ToolEvidence(
            "browser_navigate", {"url": contract.search_url},
            ToolResult.success("terbuka")),
        ToolEvidence(
            "browser_snapshot", {},
            ToolResult.success("snapshot render", snapshot=search_snapshot)),
        ToolEvidence(
            "browser_click", {"ref": "j2"},
            ToolResult.success("diklik")),
        ToolEvidence(
            "browser_snapshot", {},
            ToolResult.success("snapshot render", snapshot=watch_snapshot)),
        ToolEvidence(
            "browser_media", {
                "action": "play", "expected_video_id": "official-new",
            }, ToolResult.success({
                "found": True,
                "paused": False,
                "ended": False,
                "readyState": 4,
                "currentTime": 1.5,
                "timeAdvanced": True,
                "playing": True,
                "targetVideoId": "official-new",
                "pageVideoId": "official-new",
                "playerVideoId": "official-new",
                "targetMatched": True,
                "isAd": False,
            })),
    ]

    validation = contract.validate(evidence)

    assert validation.ok, validation.reason


def test_playback_must_follow_the_verified_watch_snapshot_without_redirect():
    contract = detect_youtube_latest_play(EXACT_TASK)
    evidence = _valid_evidence(contract)
    evidence.insert(-1, ToolEvidence(
        "browser_navigate",
        {"url": "https://www.youtube.com/watch?v=unrelated"},
        ToolResult.success("terbuka"),
    ))
    evidence.insert(-1, ToolEvidence(
        "browser_snapshot",
        {},
        {"url": "https://www.youtube.com/watch?v=unrelated",
         "text": "Channel Tidak Resmi"},
    ))

    validation = contract.validate(evidence)

    assert not validation.ok
    assert "currentTime maju" in validation.reason


def test_media_status_alone_cannot_replace_time_advance_verification():
    contract = detect_youtube_latest_play(EXACT_TASK)
    evidence = _valid_evidence(contract)
    evidence[-1] = ToolEvidence("browser_media", {"action": "status"}, {
        "found": True,
        "paused": False,
        "ended": False,
        "readyState": 4,
        "currentTime": 2.1,
        "playing": True,
    }, True)

    validation = contract.validate(evidence)

    assert not validation.ok
    assert "currentTime maju" in validation.reason


def test_contract_validator_rejects_unsorted_blind_wrong_channel_and_no_play():
    contract = detect_youtube_latest_play(EXACT_TASK)
    evidence = [
        ToolEvidence("browser_navigate", {
            "url": "https://www.youtube.com/results?search_query=deddy",
        }),
        ToolEvidence("browser_click", {
            "selector": "#first-result",
        }),
        ToolEvidence("browser_snapshot", {}, {
            "url": "https://www.youtube.com/watch?v=wrong",
            "text": "Channel Tidak Resmi",
        }),
        ToolEvidence("browser_media", {"action": "play"}, {
            "found": True,
            "paused": False,
            "ended": False,
            "readyState": 4,
            "currentTime": 3.0,
            "timeAdvanced": False,
            "playing": False,
        }),
    ]

    validation = contract.validate(evidence)

    assert not validation.ok
    assert "exact sort-by-date" in validation.reason
    assert "tanpa snapshot" in validation.reason
    assert "selector buta" in validation.reason
    assert "channel yang benar" in validation.reason
    assert "currentTime maju" in validation.reason

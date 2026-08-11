"""NotificationHub (Mark L Change 1) — post-boot notification poll.

Polls sources concurrently with a hard deadline; each source degrades to a
zero-count "limited mode" report on missing creds or errors — nothing crashes
the boot path. The spoken greeting is generated from real poll results.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta

from jarvis.core import config, log

_logger = log.get("notify")


@dataclass
class SourceResult:
    source: str
    count: int
    ok: bool
    detail: str = ""
    message: str = ""


def _get_google_creds(required_scopes: list[str]):
    """Compatibility seam: seluruh polling memakai OAuth Google terpadu."""
    try:
        from jarvis.integrations import google_auth
        return google_auth.credentials(required_scopes)
    except Exception as exc:                                 # noqa: BLE001
        _logger.info("notify.google_auth_unavailable",
                     error=type(exc).__name__)
        return None


def _google_read_scope(api: str) -> str | None:
    from jarvis.integrations import google_auth
    if not google_auth.has_read_scope(api):
        return None
    spec = google_auth.SCOPES[api]
    if google_auth.has_scope(spec.get("read", "")):
        return spec["read"]
    return spec.get("write")


def _poll_calendar() -> SourceResult:
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return SourceResult("calendar", 0, False, "Library google-api-python-client tidak ada")
        
    scope = _google_read_scope("calendar")
    creds = _get_google_creds([scope]) if scope else None
    if not creds:
        return SourceResult("calendar", 0, False, "Kredensial Google belum dikonfigurasi")
        
    try:
        service = build('calendar', 'v3', credentials=creds)
        # Time range: today
        now = datetime.utcnow()
        time_min = now.replace(hour=0, minute=0, second=0).isoformat() + 'Z'
        time_max = now.replace(hour=23, minute=59, second=59).isoformat() + 'Z'
        
        events_result = service.events().list(calendarId='primary', timeMin=time_min,
                                              timeMax=time_max, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])
        
        if not events:
            return SourceResult("calendar", 0, True, message="Anda tidak memiliki agenda hari ini.")
            
        agenda_titles = [e.get('summary', 'Agenda tanpa judul') for e in events[:3]]
        agenda_text = ", ".join(agenda_titles)
        if len(events) > 3:
            agenda_text += f" dan {len(events) - 3} agenda lainnya"
            
        return SourceResult("calendar", len(events), True, 
                            message=f"Anda memiliki {len(events)} agenda hari ini, termasuk: {agenda_text}.")
    except Exception as e:
        return SourceResult("calendar", 0, False, str(e)[:80])


def _poll_youtube() -> SourceResult:
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return SourceResult("youtube", 0, False, "Library google-api-python-client tidak ada")
        
    scope = _google_read_scope("youtube")
    creds = _get_google_creds([scope]) if scope else None
    if not creds:
        return SourceResult("youtube", 0, False, "Kredensial Google belum dikonfigurasi")
        
    try:
        yt = build('youtube', 'v3', credentials=creds)
        
        # Get channel stats
        channel_resp = yt.channels().list(part="statistics", mine=True).execute()
        if not channel_resp.get("items"):
            return SourceResult("youtube", 0, False, "Channel tidak ditemukan")
            
        stats = channel_resp["items"][0]["statistics"]
        views = stats.get("viewCount", "0")
        subs = stats.get("subscriberCount", "0")
        
        msg = f"Di channel YouTube Anda, terdapat total {views} views dan {subs} subscribers."
        
        return SourceResult("youtube", 1, True, message=msg)
    except Exception as e:
        return SourceResult("youtube", 0, False, str(e)[:80])

def _poll_email() -> SourceResult:
    try:
        scope = _google_read_scope("gmail")
        if scope:
            from googleapiclient.discovery import build
            creds = _get_google_creds([scope])
            if not creds:
                return SourceResult(
                    "email", 0, False,
                    "Kredensial Google Gmail belum tersedia")
            gmail = build("gmail", "v1", credentials=creds,
                          cache_discovery=False)
            response = gmail.users().messages().list(
                userId="me", q="is:unread", maxResults=100,
                includeSpamTrash=False).execute()
            count = int(response.get("resultSizeEstimate", 0))
            message = ("Tidak ada email baru hari ini." if count == 0 else
                       f"Anda memiliki {count} email baru yang belum dibaca.")
            return SourceResult("email", count, True, message=message)
    except ImportError:
        return SourceResult(
            "email", 0, False, "Library google-api-python-client tidak ada")
    except Exception as exc:                                 # noqa: BLE001
        return SourceResult("email", 0, False,
                            f"Gmail gagal: {type(exc).__name__}")

    try:
        import imaplib
        host = config.secret("JARVIS_IMAP_HOST", "nlp.email.imap_host")
        user = config.secret("JARVIS_IMAP_USER")
        pwd = config.secret("JARVIS_IMAP_PASSWORD")

        if not (host and user and pwd):
            return SourceResult("email", 0, False,
                                "Kredensial IMAP belum diisi (env JARVIS_IMAP_*)")

        mail = imaplib.IMAP4_SSL(host, timeout=8)
        mail.login(user, pwd)
        mail.select("inbox")
        status, response = mail.search(None, "UNSEEN")
        unread_ids = response[0].split()
        count = len(unread_ids)
        mail.logout()
        
        if count == 0:
            return SourceResult("email", 0, True, message="Tidak ada email baru hari ini.")
        return SourceResult("email", count, True, message=f"Anda memiliki {count} email baru yang belum dibaca.")
    except Exception as e:
        return SourceResult("email", 0, False, str(e)[:80])


class NotificationHub:
    _POLLERS = {"calendar": _poll_calendar, "youtube": _poll_youtube, "email": _poll_email}

    def poll(self) -> dict[str, SourceResult]:
        """Concurrent poll, deadline-bounded. Never raises."""
        timeout = float(config.get("notifications.poll_timeout_s", 8))
        results: dict[str, SourceResult] = {}
        pool = ThreadPoolExecutor(max_workers=len(self._POLLERS),
                                  thread_name_prefix="notify")
        futures = {pool.submit(fn): name for name, fn in self._POLLERS.items()}
        try:
            for fut in as_completed(futures, timeout=timeout):
                name = futures[fut]
                try:
                    results[name] = fut.result()
                except Exception as e:
                    results[name] = SourceResult(name, 0, False, str(e)[:80])
        except TimeoutError:
            pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        for name in self._POLLERS:
            results.setdefault(name, SourceResult(name, 0, False, "timeout"))
        _logger.info("notify.polled", **{
            n: {"count": r.count, "ok": r.ok, "detail": r.detail}
            for n, r in results.items()})
        return results

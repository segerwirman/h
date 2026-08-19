import webbrowser
from urllib.parse import quote_plus

from jarvis.runtime.cache import TTLCache, normalized_key
from jarvis.runtime.metrics import METRICS

_WEATHER_CACHE = TTLCache(max_entries=64)
_WEATHER_TTL_S = 600


def weather_action(
    parameters: dict,
    player=None,
    session_memory=None,
) -> str:
    city     = parameters.get("city")
    when     = parameters.get("time", "today")  

    if not city or not isinstance(city, str) or not city.strip():
        msg = "Sir, the city is missing for the weather report."
        _log(msg, player)
        return msg

    city = city.strip()
    when = (when or "today").strip()

    try:
        from jarvis.core import locale as jlocale
        loc = jlocale.resolve(city)
    except Exception:
        loc = None
    search_query = (f"cuaca {city} {when}" if loc and loc.indonesian
                    else f"weather in {city} {when}")
    url           = f"https://www.google.com/search?q={quote_plus(search_query)}"

    cache_key = normalized_key(city, when)
    started = __import__("time").perf_counter()

    def _open() -> bool:
        opened = webbrowser.open(url)
        if not opened:
            raise RuntimeError("webbrowser.open returned False")
        return True

    try:
        _WEATHER_CACHE.get_or_load(cache_key, _WEATHER_TTL_S, _open)
    except Exception as e:
        msg = f"Sir, I couldn't open the browser for the weather report: {e}"
        _log(msg, player)
        return msg
    finally:
        METRICS.record("weather.open", __import__("time").perf_counter() - started)

    msg = f"Showing the weather for {city}, {when}, sir."
    _log(msg, player)
    try:
        from jarvis.core.bus import BUS
        region = f" ({loc.region})" if loc is not None else ""
        BUS.publish("info.card", kind="weather", title=city,
                    lines=[f"Pencarian cuaca {when} dibuka{region}."],
                    source=url, ts="")
    except Exception as e:
        print(f"[Weather] info card unavailable: {e}")

    if session_memory:
        try:
            session_memory.set_last_search(query=search_query, response=msg)
        except Exception:
            pass

    return msg


def _log(message: str, player=None) -> None:
    print(f"[Weather] {message}")
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception as exc:  # noqa: BLE001
            from jarvis.core import quiet
            quiet.swallowed(
                "actions.weather_report.player_log_failed",
                exc,
                message=message,
            )

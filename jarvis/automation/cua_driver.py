"""Native Computer-Use driver with bounded, inspectable desktop actions."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScreenBounds:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


class NativeCUADriver:
    """PyAutoGUI execution backed by MSS observation and coordinate guards."""

    @staticmethod
    def _pg():
        import pyautogui

        pyautogui.FAILSAFE = True
        return pyautogui

    @staticmethod
    def monitor(display: int = 0) -> ScreenBounds:
        import mss

        with mss.MSS() as sct:
            monitors = sct.monitors
            index = int(display)
            if index < 0 or index >= len(monitors):
                index = 0
            raw = monitors[index]
        return ScreenBounds(
            int(raw["left"]),
            int(raw["top"]),
            int(raw["width"]),
            int(raw["height"]),
        )

    def ensure_point(self, x: int, y: int) -> ScreenBounds:
        bounds = self.monitor(0)
        if not bounds.contains(int(x), int(y)):
            raise ValueError(
                f"koordinat ({x},{y}) di luar desktop "
                f"{bounds.left},{bounds.top}..{bounds.right-1},{bounds.bottom-1}"
            )
        return bounds

    def screenshot(self, path: Path, display: int = 1) -> ScreenBounds:
        import mss
        import mss.tools

        with mss.MSS() as sct:
            monitors = sct.monitors
            index = int(display)
            if index <= 0 or index >= len(monitors):
                index = 1 if len(monitors) > 1 else 0
            raw = monitors[index]
            image = sct.grab(raw)
            mss.tools.to_png(image.rgb, image.size, output=str(path))
        return ScreenBounds(
            int(raw["left"]),
            int(raw["top"]),
            int(raw["width"]),
            int(raw["height"]),
        )

    def click(self, x: int, y: int, *, button: str = "left",
              double: bool = False, backend=None) -> None:
        self.ensure_point(x, y)
        if button not in {"left", "right", "middle"}:
            raise ValueError("button harus left, right, atau middle")
        pg = backend or self._pg()
        if double:
            pg.doubleClick(int(x), int(y), button=button)
        else:
            pg.click(int(x), int(y), button=button)

    def type_text(self, text: str, *, backend=None) -> None:
        (backend or self._pg()).write(str(text), interval=0.015)

    def key(self, parts: list[str], *, backend=None) -> None:
        pg = backend or self._pg()
        if len(parts) == 1:
            pg.press(parts[0])
        else:
            pg.hotkey(*parts)

    def scroll(self, x: int, y: int, dy: int, *, backend=None) -> None:
        pg = backend or self._pg()
        if x or y:
            self.ensure_point(x, y)
            pg.moveTo(int(x), int(y))
        pg.scroll(int(dy))

    def drag(self, from_x: int, from_y: int, to_x: int, to_y: int,
             duration: float, *, backend=None) -> None:
        self.ensure_point(from_x, from_y)
        self.ensure_point(to_x, to_y)
        pg = backend or self._pg()
        pg.moveTo(int(from_x), int(from_y))
        pg.dragTo(
            int(to_x),
            int(to_y),
            duration=max(0.1, min(float(duration), 3.0)),
            button="left",
        )


DRIVER = NativeCUADriver()


__all__ = ["DRIVER", "NativeCUADriver", "ScreenBounds"]

"""Studio A: hidden desktop-local project and scene planning sheet."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

from jarvis.core.content_project import ContentProject, Scene
from jarvis.core.content_title_policy import admit_title
from jarvis.core.content_scene_reorder import admit_reorder, apply_reorder
from jarvis.ui import theme


class ContentStudioSheet(QWidget):
    """Local planning surface; provider, browser, and publishing are absent."""

    studio_focus_requested = pyqtSignal(bool)
    _SECTIONS = ("Brief", "Brainstorm", "Timeline")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")
        self._title = self._audience = self._tone = self._hook = self._cta = ""
        self._scenes: list[Scene] = []
        self._selected_scene: int | None = None
        self._asset: dict | None = None
        layout = QVBoxLayout(self)
        heading = QLabel("CONTENT STUDIO — LOKAL")
        heading.setFont(theme.header_font(13))
        heading.setStyleSheet(f"color:{theme.PAL.accent}; background:transparent;")
        layout.addWidget(heading)
        layout.addWidget(QLabel("Brief · Brainstorm · Timeline"))
        self._status = QLabel("Siap menyusun project lokal.")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._focus_button = QPushButton("FOCUS ON")
        self._focus_button.clicked.connect(self._toggle_studio_focus)
        layout.addWidget(self._focus_button)
        self._studio_focus_active = False
        self._field_refs: dict[str, QLineEdit] = {}
        for label in ("Judul", "Audiens", "Tone", "Hook", "CTA"):
            field = QLineEdit()
            field.setPlaceholderText(label)
            self._field_refs[label.casefold()] = field
            layout.addWidget(field)
        notes = QTextEdit()
        notes.setPlaceholderText("Catatan brainstorming lokal")
        layout.addWidget(notes)
        # ── Phase 22: scene list production UX ──
        self._scene_list = QListWidget()
        self._scene_list.setObjectName("jarvis-scene-list")
        self._scene_list.setAccessibleName("Daftar Scene")
        self._scene_list.itemClicked.connect(self._on_scene_clicked)
        layout.addWidget(self._scene_list)
        move_row = QWidget()
        move_layout = QHBoxLayout(move_row)
        self._move_up_button = QPushButton("▲ Naik")
        self._move_up_button.setObjectName("jarvis-scene-move-up")
        self._move_up_button.setAccessibleName("Pindahkan scene ke atas")
        self._move_up_button.clicked.connect(lambda: self.move_selected_up())
        self._move_down_button = QPushButton("▼ Turun")
        self._move_down_button.setObjectName("jarvis-scene-move-down")
        self._move_down_button.setAccessibleName("Pindahkan scene ke bawah")
        self._move_down_button.clicked.connect(lambda: self.move_selected_down())
        move_layout.addWidget(self._move_up_button)
        move_layout.addWidget(self._move_down_button)
        layout.addWidget(move_row)
        self._render_scene_list()
        self.hide()

    def section_names(self) -> tuple[str, ...]:
        return self._SECTIONS

    def status_text(self) -> str:
        return self._status.text()

    def set_studio_focus_active(self, active: bool) -> None:
        self._studio_focus_active = bool(active)
        self._focus_button.setText("FOCUS OFF" if self._studio_focus_active else "FOCUS ON")

    def _toggle_studio_focus(self) -> None:
        self.studio_focus_requested.emit(not self._studio_focus_active)

    # ── Phase 19: intent-specific bounded setter for Judul Project only ──

    def set_project_title(self, title: object) -> dict:
        """Set only the Judul Project field through bounded policy.

        Intent is fixed to ``content_studio_title``. No generic field routing,
        no other field mutation, no URL/password/payment/terminal acceptance.
        Returns safe metadata only.
        """
        result = admit_title(title)
        if not result.get("ok"):
            self._status.setText("Judul project tidak valid.")
            return {"ok": False, "reason": result.get("reason", "content_title_rejected")}

        clean = result["title"]
        self._title = clean
        field = self._field_refs.get("judul")
        if field is not None:
            # local UI sync only, no generic dispatch
            try:
                field.setText(clean)
            except Exception:
                pass
        self._status.setText("Judul project lokal diperbarui.")
        return {"ok": True, "title": clean, "intent": "content_studio_title"}

    def set_project_fields(self, *, title: str, audience: str, tone: str, hook: str, cta: str) -> None:
        self._title, self._audience, self._tone = str(title).strip(), str(audience).strip(), str(tone).strip()
        self._hook, self._cta = str(hook).strip(), str(cta).strip()
        self._status.setText("Project lokal diperbarui.")

    def add_scene(self, *, title: str, visual: str, narration: str, visual_prompt: str) -> bool:
        values = (title, visual, narration, visual_prompt)
        if not all(isinstance(value, str) and value.strip() for value in values):
            self._status.setText("Scene belum lengkap.")
            return False
        self._scenes.append(Scene(*(value.strip() for value in values)))
        self._status.setText("Scene lokal ditambahkan.")
        self._render_scene_list()
        return True

    def project(self) -> ContentProject:
        return ContentProject(self._title, self._audience, self._tone, self._hook, self._cta, tuple(self._scenes))

    def timeline_rows(self) -> list[dict]:
        """Local scene timeline; asset state reflects the last generated scene only."""
        from jarvis.core.content_export import build_timeline
        assets = {self._asset["scene_index"]: self._asset} if self._asset else {}
        return build_timeline(self.project(), assets=assets)

    def export_project(self, fmt: str) -> dict:
        """Bounded local export of project-owned content; reject unsafe formats."""
        from jarvis.core.content_export import export_project
        assets = {self._asset["scene_index"]: self._asset} if self._asset else {}
        result = export_project(self.project(), fmt=fmt, assets=assets)
        if result.get("ok"):
            self._status.setText("Ekspor lokal siap.")
        else:
            self._status.setText("Format ekspor tidak didukung.")
        return result

    def select_scene(self, index: int) -> bool:
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(self._scenes):
            self._status.setText("Pilih satu scene yang valid.")
            return False
        self._selected_scene = index
        self._status.setText("Scene dipilih untuk gambar lokal.")
        self._render_scene_list()
        return True

    def move_scene(self, from_index: object, to_index: object) -> dict:
        """Bounded same-surface reorder of scene list only.

        Intent fixed to ``content_studio_scene_reorder``. No filesystem,
        no net, no bwr, no coordinate. Uses admit_reorder policy.
        Returns safe metadata only, never path/secret.
        """
        result = admit_reorder(from_index, to_index, len(self._scenes))
        if not result.get("ok"):
            self._status.setText("Urutan scene tidak valid.")
            return {"ok": False, "reason": result.get("reason", "content_reorder_rejected")}

        f = int(result["from_index"])
        t = int(result["to_index"])
        # preserve selected mapping
        selected = self._selected_scene
        self._scenes = apply_reorder(self._scenes, f, t)

        # update selected index after reorder
        if selected is not None:
            if selected == f:
                self._selected_scene = t
            elif f < selected <= t:
                self._selected_scene = selected - 1
            elif t <= selected < f:
                self._selected_scene = selected + 1

        # asset mapping mengikuti scene yang sama setelah reorder
        if self._asset is not None:
            asset_index = self._asset.get("scene_index")
            if isinstance(asset_index, int):
                if asset_index == f:
                    self._asset["scene_index"] = t
                elif f < asset_index <= t:
                    self._asset["scene_index"] = asset_index - 1
                elif t <= asset_index < f:
                    self._asset["scene_index"] = asset_index + 1

        self._render_scene_list()
        self._status.setText("Urutan scene lokal diperbarui.")
        return {"ok": True, "from_index": f, "to_index": t, "intent": "content_studio_scene_reorder"}

    def asset_metadata(self) -> dict | None:
        return dict(self._asset) if self._asset else None

    async def generate_selected_scene(self) -> dict:
        if self._selected_scene is None:
            return {"ok": False, "reason": "content_scene_selection_required"}
        from jarvis.core.content_assets import generate_selected_scene_with_active_provider
        result = await generate_selected_scene_with_active_provider(self.project(), self._selected_scene)
        if result.get("ok"):
            self._asset = dict(result["asset"])
            self._status.setText("Gambar scene lokal siap.")
        else:
            self._status.setText("Gambar scene belum tersedia.")
        return result


    def scene_list_widget(self):
        """Widget daftar scene (Phase 22) — identity stabil untuk lane UIA."""
        return self._scene_list

    def move_up_button(self):
        return self._move_up_button

    def move_down_button(self):
        return self._move_down_button

    def selected_scene(self) -> int | None:
        return self._selected_scene

    def _on_scene_clicked(self, item) -> None:
        self.select_scene(self._scene_list.row(item))

    def _render_scene_list(self) -> None:
        """Render ulang daftar scene dari _scenes lokal + state kontrol."""
        self._scene_list.clear()
        for index, scene in enumerate(self._scenes):
            self._scene_list.addItem(f"{index + 1}. {scene.title}")
        count = len(self._scenes)
        has_selection = self._selected_scene is not None and 0 <= self._selected_scene < count
        if has_selection:
            self._scene_list.setCurrentRow(int(self._selected_scene))
        self._move_up_button.setEnabled(has_selection and self._selected_scene != 0)
        self._move_down_button.setEnabled(
            has_selection and self._selected_scene != count - 1)

    def move_selected_up(self) -> bool:
        """Pindahkan scene terpilih satu langkah ke atas (first-up reject)."""
        if self._selected_scene is None:
            return False
        return bool(self.move_scene(
            self._selected_scene, self._selected_scene - 1).get("ok"))

    def move_selected_down(self) -> bool:
        """Pindahkan scene terpilih satu langkah ke bawah (last-down reject)."""
        if self._selected_scene is None:
            return False
        return bool(self.move_scene(
            self._selected_scene, self._selected_scene + 1).get("ok"))


__all__ = ["ContentStudioSheet"]

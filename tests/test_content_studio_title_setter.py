"""ContentStudioSheet intent-specific title setter."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
_APP = None

def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP

def test_title_setter_is_missing_is_red():
    _app()
    from jarvis.ui.content_studio import ContentStudioSheet
    sheet = ContentStudioSheet()
    # RED: method must exist for GREEN; if missing we assert RED
    assert hasattr(sheet, "set_project_title"), "RED: set_project_title must exist after implementation"

def test_set_project_title_accepts_bounded_title():
    _app()
    from jarvis.ui.content_studio import ContentStudioSheet
    sheet = ContentStudioSheet()
    if not hasattr(sheet, "set_project_title"):
        return
    res = sheet.set_project_title("  Peluncuran Lokal  ")
    assert res["ok"] is True
    assert res["title"] == "Peluncuran Lokal"
    assert res["intent"] == "content_studio_title"
    assert sheet.project().title == "Peluncuran Lokal"
    assert "siap" in sheet.status_text().lower() or "diperbarui" in sheet.status_text().lower()

def test_set_project_title_rejects_non_bounded():
    _app()
    from jarvis.ui.content_studio import ContentStudioSheet
    sheet = ContentStudioSheet()
    if not hasattr(sheet, "set_project_title"):
        return
    sheet.set_project_title("Awal")
    assert sheet.project().title == "Awal"
    bad = sheet.set_project_title("https://evil.com")
    assert bad["ok"] is False
    # must NOT overwrite previous valid title
    assert sheet.project().title == "Awal"

def test_set_project_title_rejects_password_url_oversize():
    _app()
    from jarvis.ui.content_studio import ContentStudioSheet
    sheet = ContentStudioSheet()
    if not hasattr(sheet, "set_project_title"):
        return
    for txt in ["password 123", "OTP 123", "x"*201, "payment checkout"]:
        res = sheet.set_project_title(txt)
        assert res["ok"] is False, f"should reject {txt!r}"

def test_set_project_title_only_affects_title_field():
    _app()
    from jarvis.ui.content_studio import ContentStudioSheet
    sheet = ContentStudioSheet()
    if not hasattr(sheet, "set_project_title"):
        return
    sheet.set_project_fields(title="Old", audience="Kreator", tone="Cinematic", hook="Mulai", cta="Coba")
    sheet.set_project_title("Baru")
    proj = sheet.project()
    assert proj.title == "Baru"
    assert proj.audience == "Kreator"
    assert proj.tone == "Cinematic"

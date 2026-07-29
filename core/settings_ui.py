from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QCheckBox, QMessageBox)
from PyQt6.QtCore import Qt
import json
from pathlib import Path

from jarvis.core import secrets_store

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jarvis Settings")
        self.resize(400, 200)
        self.setStyleSheet("background-color: #000308; color: #00FF88; font-family: 'Courier New';")
        
        self.config_path = Path(__file__).parent.parent / "config" / "api_keys.json"
        
        layout = QVBoxLayout(self)
        
        # Gestures toggle
        self.cb_gestures = QCheckBox("Enable Hand Gestures (MediaPipe)")
        self.cb_gestures.setStyleSheet("QCheckBox { padding: 5px; font-weight: bold; }")
        
        # Gemini API Key
        api_layout = QHBoxLayout()
        api_label = QLabel("Gemini API Key:")
        self.api_input = QLineEdit()
        self.api_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.api_input.setStyleSheet("background: #001A22; border: 1px solid #00FF88; color: #00FF88; padding: 5px;")
        api_layout.addWidget(api_label)
        api_layout.addWidget(self.api_input)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Save && Apply")
        self.btn_save.setStyleSheet("QPushButton { background: #003322; border: 1px solid #00FF88; padding: 7px; font-weight: bold; } QPushButton:hover { background: #005533; }")
        self.btn_save.clicked.connect(self.save_config)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("QPushButton { background: #330000; border: 1px solid #FF0044; padding: 7px; font-weight: bold; } QPushButton:hover { background: #550000; }")
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        
        layout.addWidget(self.cb_gestures)
        layout.addLayout(api_layout)
        layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.load_config()

    def load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        except Exception:
            self.config = {}
            
        self.cb_gestures.setChecked(self.config.get("enable_gestures", True))
        self.config.pop("gemini_api_key", None)
        self.api_input.setText(
            secrets_store.get("jarvis/llm/gemini") or "")

    def save_config(self):
        self.config["enable_gestures"] = self.cb_gestures.isChecked()
        key = self.api_input.text().strip()
        if key and not secrets_store.set("jarvis/llm/gemini", key):
            QMessageBox.warning(
                self, "Secret Store Tidak Tersedia",
                "API key tidak disimpan karena backend terenkripsi tidak "
                "tersedia.")
            return
        self.config.pop("gemini_api_key", None)
        
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4)
        
        self.accept()

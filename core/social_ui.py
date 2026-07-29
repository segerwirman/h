from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox
from PyQt6.QtCore import Qt
from core.social_manager import SocialManager

class SocialConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Social Media Configuration")
        self.resize(300, 200)
        self.setStyleSheet("background-color: #000308; color: #00FF88;")
        self.manager = SocialManager()
        
        layout = QVBoxLayout(self)
        
        self.cb_facebook = QCheckBox("Enable Facebook")
        self.cb_x = QCheckBox("Enable X (Twitter)")
        self.cb_instagram = QCheckBox("Enable Instagram")
        self.cb_tiktok = QCheckBox("Enable TikTok")
        
        creds = self.manager.load_config()
        self.cb_facebook.setChecked(creds.get("facebook", False))
        self.cb_x.setChecked(creds.get("x", False))
        self.cb_instagram.setChecked(creds.get("instagram", False))
        self.cb_tiktok.setChecked(creds.get("tiktok", False))
        
        layout.addWidget(self.cb_facebook)
        layout.addWidget(self.cb_x)
        layout.addWidget(self.cb_instagram)
        layout.addWidget(self.cb_tiktok)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setStyleSheet("background-color: #003311; border: 1px solid #00FF88; padding: 5px;")
        save_btn.clicked.connect(self.save)
        
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("background-color: #330000; border: 1px solid #FF0033; padding: 5px; color: #FF0033;")
        close_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        
    def save(self):
        creds = {
            "facebook": self.cb_facebook.isChecked(),
            "x": self.cb_x.isChecked(),
            "instagram": self.cb_instagram.isChecked(),
            "tiktok": self.cb_tiktok.isChecked()
        }
        self.manager.save_config(creds)
        self.accept()

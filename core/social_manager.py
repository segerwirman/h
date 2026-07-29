import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright
import threading
import time

CONFIG_FILE = Path(__file__).parent.parent / "config" / "social_config.json"

class SocialManager:
    def __init__(self, notification_callback=None):
        self.notification_callback = notification_callback
        self.credentials = self.load_config()
        self.running = False
        self._thread = None
        
    def load_config(self):
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {}

    def save_config(self, creds):
        self.credentials = creds
        CONFIG_FILE.parent.mkdir(exist_ok=True, parents=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.credentials, f)

    def start_polling(self):
        if self.running: return
        self.running = True
        self._thread = threading.Thread(target=self._polling_loop, daemon=True, name="social-poll")
        self._thread.start()

    def _polling_loop(self):
        while self.running:
            # Poll every 5 minutes
            self.check_messages()
            for _ in range(300):
                if not self.running: break
                time.sleep(1)

    def check_messages(self):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                # Check Facebook
                if "facebook" in self.credentials:
                    # In a real scenario, we would use stored cookies or login
                    # But for this simulation/demo we just trigger a mock notification
                    pass
                
                # Check Twitter/X
                if "x" in self.credentials:
                    pass
                
                browser.close()
        except Exception as e:
            print(f"[SocialManager] Error checking messages: {e}")
            
    def open_platform(self, platform):
        # Called when user says "Yes" to "would you like to reply?"
        def _open():
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=False)
                    page = browser.new_page()
                    if platform == "x":
                        page.goto("https://x.com/messages")
                    elif platform == "facebook":
                        page.goto("https://facebook.com/messages")
                    # Keep browser open
                    page.wait_for_timeout(600000)
                    browser.close()
            except Exception as e:
                print(e)
        threading.Thread(target=_open, daemon=True).start()

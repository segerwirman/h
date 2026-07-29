import threading
import numpy as np
import sounddevice as sd
import speech_recognition as sr
from core import tts

class VoiceListener:
    def __init__(self, on_wake_word_callback=None, interrupt_threshold=0.03):
        self.on_wake_word_callback = on_wake_word_callback
        self.interrupt_threshold = interrupt_threshold
        self.running = False
        self._thread = None
        
    def start(self):
        if self.running: return
        self.running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name="voice-listener")
        self._thread.start()
        
    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            
    def _listen_loop(self):
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 300
        recognizer.dynamic_energy_threshold = True
        
        # Audio stream for continuous volume monitoring (interruption)
        # We will use a separate thread for wake word to not block volume checking
        wake_word_thread = threading.Thread(target=self._wake_word_loop, args=(recognizer,), daemon=True)
        wake_word_thread.start()
        
        def audio_callback(indata, frames, time, status):
            if not self.running:
                raise sd.CallbackAbort
            # Calculate RMS
            rms = np.sqrt(np.mean(indata**2))
            if rms > self.interrupt_threshold:
                # If someone is speaking loudly while TTS is playing, interrupt!
                if not tts.INTERRUPT_FLAG:
                    tts.INTERRUPT_FLAG = True
                    
        with sd.InputStream(callback=audio_callback, channels=1, samplerate=16000):
            while self.running:
                sd.sleep(100)

    def _wake_word_loop(self, recognizer):
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
            while self.running:
                try:
                    # Listen in short bursts
                    audio = recognizer.listen(source, timeout=1, phrase_time_limit=3)
                    text = recognizer.recognize_google(audio).lower()
                    if "jarvis" in text:
                        if self.on_wake_word_callback:
                            self.on_wake_word_callback()
                except sr.WaitTimeoutError:
                    pass
                except sr.UnknownValueError:
                    pass
                except Exception as e:
                    print(f"[VoiceListener] Error: {e}")

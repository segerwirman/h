"""Provider model discovery methods extracted from the settings sheet."""
from __future__ import annotations

import threading


class ProviderDiscoveryMixin:
    def _update_vision_support(self, model: str = "") -> None:
        """Auto-tentukan apakah provider+model yang dipilih mendukung vision.

        Vision ditentukan dari capability provider (deklaratif) — bukan tebakan
        nama model. Bila didukung dan kolom vision model kosong, isi otomatis
        dengan model terpilih agar jalur vision langsung siap.
        """
        from jarvis.agent import providers
        name = self._combo.currentText()
        try:
            supports = providers.get_provider(name).supports("vision")
        except Exception:                                    # noqa: BLE001
            supports = False
        if supports:
            self._vision_hint.setText("Vision: didukung ✓ (provider ini)")
            if model and not self._vision_model.text().strip():
                self._vision_model.setText(model)
        else:
            self._vision_hint.setText("Vision: tidak didukung provider ini")

    def _detect_models(self) -> None:
        """Tes koneksi = discovery katalog 5 detik pada worker UI-safe."""
        name = self._combo.currentText()
        self._set_detected_models(())
        self._show_manual_fallback(False)
        self._set_connection_status("● Menguji koneksi dan mendeteksi model …", "testing")
        # Jangan persist credential hanya untuk tes. Snapshot draft dipakai
        # worker, lalu SIMPAN tetap menjadi aksi eksplisit user.
        from dataclasses import replace
        from jarvis.agent import providers
        stored = providers.get_provider(name)
        draft = replace(
            stored,
            base_url=self._base_url.text().strip() or stored.base_url,
            api_key=self._api_key.text().strip() or stored.api_key,
        )

        def worker() -> None:
            try:
                from jarvis.agent import providers_discovery
                models = providers_discovery.discover(draft)
                payload = {"provider": name, "state": "models_detected",
                           "models": models}
            except Exception as exc:  # safe discovery errors only
                from jarvis.agent import providers_discovery
                payload = {"provider": name, "state": "models_failed",
                           "error": str(exc),
                           "manual": isinstance(exc, providers_discovery.DiscoveryError)
                           and providers_discovery.manual_fallback_allowed(exc)}
            try:
                self._model_catalog_updated.emit(payload)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True,
                         name=f"{name}-model-discovery").start()

    def _apply_model_catalog(self, state: dict) -> None:
        name = str(state.get("provider") or "")
        if name != self._combo.currentText():
            return
        if state.get("state") == "agent_probe":
            result = state.get("result")
            if getattr(result, "ready", False):
                self._set_connection_status(
                    "● Agent siap — chat dan native tool calling terverifikasi.",
                    "ok",
                )
            elif getattr(result, "chat_ok", False):
                self._set_connection_status(
                    "● Chat terhubung, tetapi native tool calling belum "
                    "terverifikasi. Pilih model yang mendukung tools.",
                    "error",
                )
            else:
                self._set_connection_status(
                    "● Tes model belum berhasil. Periksa konfigurasi lalu coba lagi.",
                    "error",
                )
            return
        if state.get("state") == "models_failed":
            self._set_detected_models(())
            manual = bool(state.get("manual"))
            self._show_manual_fallback(manual)
            if manual:
                message = "● Gagal — format katalog tidak dikenali. Masukkan model manual."
            else:
                message = "● Koneksi provider belum tersedia. Periksa konfigurasi lalu coba lagi."
            self._set_connection_status(message, "error")
            return
        models = tuple(state.get("models", ()))
        self._set_detected_models(models)
        self._show_manual_fallback(False)
        self._set_connection_status(
            f"● Terhubung — {len(models)} model ditemukan. "
            "Klik TEST NATIVE AGENT MODEL untuk verifikasi tool calling."
            if models else "● Terhubung, tetapi provider tidak memberi model yang dapat dipilih.",
            "ok")

    def _probe_selected_agent_model(self) -> None:
        """Tes chat + function calling; tidak menjalankan tool sungguhan."""

        from dataclasses import replace
        from jarvis.agent import providers

        name = self._combo.currentText()
        stored = providers.get_provider(name)
        draft = replace(
            stored,
            base_url=self._base_url.text().strip() or stored.base_url,
            api_key=self._api_key.text().strip() or stored.api_key,
            model=self._model.text().strip() or stored.model,
        )
        self._set_connection_status(
            "● Katalog terhubung — menguji native tool calling …", "testing")

        def worker() -> None:
            from jarvis.agent import provider_probe

            result = provider_probe.probe(draft)
            try:
                self._model_catalog_updated.emit({
                    "provider": name,
                    "state": "agent_probe",
                    "result": result,
                })
            except RuntimeError:
                pass

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"{name}-agent-probe",
        ).start()

    def _test(self) -> None:
        """Kompatibilitas tombol TEST lama: kini selalu discovery non-blocking."""
        self._detect_models()



# WhatsApp Web/Desktop automation

Jarvis can open a dedicated WhatsApp Web profile, send an allowlisted message,
start/answer/end a voice call, and optionally bridge the call audio directly
to Gemini Live.

The implemented desktop mode is a dedicated, visible Chrome window running
WhatsApp Web. It intentionally does not click the native Microsoft Store
WhatsApp application, whose accessibility tree and update cadence do not
provide a dependable automation contract.

This is consumer-web automation, not the official WhatsApp Business Calling
API. WhatsApp may change its page structure or roll calling out gradually.
The adapter therefore fails closed when an accessibility-labelled control is
not found.

## Safety defaults

- The `whatsapp_web.enabled` master toggle controls whether the tools are
  exposed.
- Uses a dedicated Chrome profile, not the user's normal browser profile.
- Direct phone numbers are denied by default.
- Contacts must be explicitly allowlisted.
- Message, call, and answer tools always require confirmation.
- The model sees only contact names and a four-digit phone hint.
- No automatic answer.
- Audio bridge is disabled until two virtual devices are configured.
- No Hermes CLI dependency.

## Enable

Install the agent/browser and voice dependencies:

```powershell
python -m pip install -e ".[voice,agent]"
python -m playwright install chromium
```

In `config.yaml`:

```yaml
whatsapp_web:
  enabled: true
  headless: false
```

Copy `config/whatsapp_contacts.example.json` to
`data/whatsapp_contacts.json`, then enter contacts in international format
without `+`, spaces, or punctuation:

```json
{
  "contacts": [
    {
      "name": "Ibu",
      "aliases": ["Mama", "Ibu rumah"],
      "phone": "628123456789",
      "allowed": true
    }
  ]
}
```

The `data/` directory is ignored by Git.

Start Jarvis, then ask:

```text
Jarvis, buka WhatsApp.
```

On first use, scan the QR code in the dedicated Chrome window.
Restart Jarvis after changing `whatsapp_web.enabled`, because the tool registry
is snapshotted when a new runtime starts.

## Commands

Examples:

```text
Jarvis, telepon Ibu lewat WhatsApp.
Jarvis, telepon Ibu.
Jarvis, jawab panggilan WhatsApp.
Jarvis, akhiri panggilan WhatsApp.
Jarvis, cek status WhatsApp.
Jarvis, kirim pesan WhatsApp ke Ibu: Saya terlambat sepuluh menit.
```

Before external communication Jarvis asks for confirmation through the normal
agent approval boundary.

## Let Jarvis speak in the call

Browser calls use operating-system audio devices. For a digital, echo-free
bridge, install two independent virtual audio cables:

1. Select cable A as the WhatsApp Web speaker. Configure cable A's capture
   endpoint as `remote_input_device`.
2. Select cable B's playback endpoint as `remote_output_device`. Select cable
   B's capture endpoint as the WhatsApp Web microphone.
3. Never use one cable for both directions; that creates a feedback loop.

Ask Jarvis to run `whatsapp_audio_devices`, then configure the exact input and
output names it reports:

```yaml
whatsapp_web:
  audio_bridge:
    enabled: true
    remote_input_device: "CABLE-A Output"
    remote_output_device: "CABLE-B Input"
    monitor_local_output: true
```

Audio path:

```text
WhatsApp speaker
  → virtual cable A
  → PCM 16 kHz
  → Gemini Live input
  → Jarvis PCM 24 kHz
  → virtual cable B
  → WhatsApp microphone
```

The regular PC microphone is paused while the bridge is active. Jarvis output
is still played locally when `monitor_local_output` is true.

## Limitations

- Calling must already be available on the linked WhatsApp Web account.
- DOM selectors may require an update after a WhatsApp UI release.
- Group calls and video calls are intentionally unsupported.
- Contact lookup prefers exact name, alias, or phone matches. A conservative
  fuzzy match is accepted only when it has one clear winner inside the
  allowlist. Add aliases for speech-recognition variations you use often.
- A visible browser is required for reliable WebRTC calling.
- Placing, answering, and ending calls works without the audio bridge, but
  Jarvis can only hear and speak inside the call after two distinct virtual
  audio devices have been configured.
- This adapter does not bypass WhatsApp consent, account, or regional rules.
- For a production customer-service deployment, use the official WhatsApp
  Business Calling API instead.

## Troubleshooting

`login_required`
: Scan the QR in the dedicated Jarvis Chrome profile.

`Tombol panggilan suara tidak ditemukan`
: Verify calling has reached the account, open the contact manually, and
check that the Chrome profile is logged in.

`Dua virtual audio device wajib dikonfigurasi`
: Calls can still be used manually; configure two virtual cables before
letting Jarvis participate in the conversation.

`Kontak tidak ditemukan` or a wrong speech transcription
: Add common pronunciations to the contact's `aliases` array. Jarvis never
uses fuzzy matching to escape the allowlist.

`virtual audio tidak siap`
: Confirm device names, sample-rate support, and that another application does
not hold an exclusive lock.

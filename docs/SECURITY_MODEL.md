# Security Model

## Default posture

Jarvis is local-first and fail-closed. Optional integrations remain disabled until explicitly configured and paired.

| Boundary | Default | Guard |
|---|---|---|
| Remote gateway | Deny | Platform/actor pairing, idempotency, restricted toolsets |
| Desktop control | Local only | Execution policy plus approval boundary |
| Memory | Scoped | Owner matching; remote actors never inherit local/user memory |
| Plugins/MCP | Disabled/trusted-local | Manifest/spec validation, collision checks, allowlists |
| Operations | Local admin | RBAC, safe snapshots, redacted audit metadata |
| WhatsApp webhook | Deny | Constant-time verification token check |

## Secret handling

No operation/status/audit DTO includes plaintext credentials, OAuth tokens, raw callback data, private paths, raw task output, or full transport errors. Export/search excerpts redact credential-like `token=`, `api_key=`, `password=`, and `secret=` patterns.

## Incident response

1. Apply `safe-mode` preset.
2. Revoke gateway pairings.
3. Disable plugins/MCP/gateway subsystems.
4. Preserve redacted audit metadata; rotate affected external credentials outside Jarvis.
5. Re-enable in rollout rings only after focused verification.

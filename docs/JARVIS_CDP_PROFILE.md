# JARVIS dedicated Chrome CDP profile

The `browser_*` tools use a Chrome profile owned by JARVIS. This lane is
separate from `user_browser_*`, which is attach-only for the user's everyday
Chrome. It is also separate from `browser.agent_cli`, which remains a CDP
client unless its owner bridge is explicitly enabled.

## Defaults

- User Data directory: `%LOCALAPPDATA%\JARVIS\ChromeCDPProfile`
- Address: `127.0.0.1` only
- Port: `9333`
- Startup bound: `agent.browser.cdp.startup_timeout_s`
- Close bound: `agent.browser.cdp.close_timeout_s`

The directory must not be inside the repository, the standard Chrome User Data
tree, or a path named `Profile 8`. JARVIS never copies Local State, cookies,
tokens, credentials, extensions, or profile databases into this lane.

## Ownership and lifecycle

`_BrowserHost` is the single launch, readiness, attach, lease, and close owner.
Concurrent ensure calls converge on that host; they do not launch a second
Chrome. The endpoint is preflighted before launch. If an unknown process already
answers on port `9333`, JARVIS fails closed and neither attaches to nor closes
that process.

Shutdown is graceful and bounded. JARVIS closes only the context it launched,
then verifies that the owned endpoint disappears. A worker survivor or reachable
endpoint is reported as a timeout/failure; JARVIS does not force-kill Chrome and
does not retry indefinitely. Shutdown callbacks do not create a browser merely
to stop one.

## P3-A operational observation

One separately authorized empty-profile observation reached aggregate state
`owned: true`, `ready: true`, and `state: accepting` on the dedicated loopback
endpoint. The single bounded close then returned `closed: true`,
`owned: false`, `ready: false`, and `state: stopped`. No page metadata or user
browser data was inspected; this observation does not upgrade the `Profile 8`
lane and does not establish provider, audio, hardware, or Gemini Live evidence.

## Evidence labels

Implementation inspection and offline fake tests can establish only:

- `source-present`
- `configured`
- `focused-tested`
- `fixture-accepted`
- `not-run`

`runtime-wired` requires separate evidence that the intended runtime caller is
connected to this owner; fake seams alone do not establish it. A separately
authorized local empty-profile observation may establish `endpoint-reachable`
and `live-proven`, but only for that exact dedicated endpoint fact. A readiness
failure is `endpoint-unreachable`; it is not evidence that the user's everyday
Chrome lacks tabs or media.

Dedicated-profile evidence never upgrades the `Profile 8` lane. No Profile 8
navigation, tab inspection, media control, or mutation is part of this contract.

## Operational boundary

Implementation and fake/offline verification do not launch Chrome, access the
user's browser, navigate, inspect DOM, use credentials, call providers, or start
Gemini Live/audio. A later live check requires a separate operational approval
for one narrow empty-profile ensure/status/close run. Gemini Live, microphone,
speaker, and audio-session validation remain independent decisions.

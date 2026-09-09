# config/

Trust configuration. This directory is mounted **read-only** into the bot
container and writable only in the broker, so plugin code — which runs inside
the bot's process — cannot mark its own source as trusted or add a source of
its own. Change it from the dashboard, or edit it here and restart the broker.

- `sources.json` — plugin repositories the browser offers, and whether each is
  trusted. A plugin installed from an untrusted source is refused sidecar
  containers by the broker.
- `installed.json` — written by the broker: which source each installed plugin
  came from. Do not edit by hand.

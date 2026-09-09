# Changelog

Doppler's own version. The plugin API is versioned separately — a plugin
declares the API it targets in its `plugin.json`, and that contract changes
much less often than the bot around it.

## 0.1.0 — unreleased

First versioned build. The bot was rebuilt around plugins: it now ships with no
features of its own and assembles them from a plugin source.

### Plugin system

- Plugins are self-contained folders with a `plugin.json` manifest, installed
  from GitHub sources through the dashboard's **Plugins → Browse** tab.
- A plugin declares its settings in code; the dashboard generates the form.
  Settings are namespaced per plugin, and reading an undeclared key is an error
  rather than a silent miss.
- `ctx.db` gives each plugin its own SQLite database.
- `ctx.ai` and `ctx.translate` perform provider calls without handing the
  plugin an API key.
- `ctx.services` lets a plugin declare a sidecar container in its manifest.
- Plugins can be enabled, configured and reloaded from the dashboard while the
  bot stays connected.

### Broker

- A separate `broker` container is the only component with access to the Docker
  socket; the bot, which runs plugin code, has none.
- It starts the sidecar containers plugins declare — unprivileged, memory
  capped, no published ports, no host mounts beyond the plugin's own files.
- It installs plugins, owns the trust configuration, and holds the AI and
  translation API keys, making those calls itself.

### Trust

- `config/` and `plugins/` are mounted read-only into the bot, so plugin code
  cannot mark its own source trusted or overwrite another plugin's files.
- A plugin from an untrusted source is refused sidecar containers.
- `.env` is no longer visible in the bot container.

### Migrated from the previous version

Existing settings move to their new homes on first start: per-plugin
namespaces, per-plugin databases, and the broker's credential store. Nothing
needs to be re-entered.

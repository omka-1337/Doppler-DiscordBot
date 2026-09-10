# Changelog

Doppler's own version. The plugin API is versioned separately — a plugin
declares the API it targets in its `plugin.json`, and that contract changes
much less often than the bot around it.

## 0.2.0 — 2026-09-10

Plugin API 1.1.

### Added

- `/bot-info` — a slash command listing the bot version, plugin API version and
  every running plugin with its own version.
- Plugins may ship an HTML page of their own, rendered in a sandboxed frame with
  a tab in the dashboard. Trusted sources only.
- `doppler.bot()` in the page bridge, returning the bot's name and avatar so a
  page can preview a message without declaring an endpoint for it.
- The plugin API reference gained a **Pages** section documenting the bridge.

### Changed

- The embed builder moved out of the dashboard and into the embed plugin's own
  page; the dashboard no longer carries an Embeds tab.
- A plugin's tab now appears and disappears as it is enabled, reloaded,
  installed or uninstalled, without reloading the dashboard.

### Fixed

- A failed `doppler.bot()` lookup now rejects instead of resolving with the
  error body, which had left pages silently showing a placeholder.

### Removed

- The undocumented `tab` field in a manifest's `page` block. It never had a
  working dashboard implementation and its handler had been deleted.

## 0.1.0 — 2026-09-09

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

### First-run setup

- A setup page is shown until a bot token and an OAuth2 client secret are both
  configured; nothing else in the dashboard is reachable until then, so login is
  in place before the panel ever is.
- Both values are verified against Discord — the token by identifying the
  application, the secret by performing a client-credentials grant — and saving
  re-checks them server-side rather than trusting the browser.

### Removed

- The `cogs/` package is gone. `cogmanager` managed the old module system and
  no longer worked against anything that exists; the `/web` command handed out
  the dashboard's address, which you must already have visited to configure the
  bot at all. With both gone the bot loads nothing but plugins.
- `DASHBOARD_URL` and `WEB_PORT` went with the `/web` command — nothing else
  read them.
- Prefix commands are gone entirely: the bot is slash-only, so the command
  prefix setting and discord.py's default `!help` went with them.

### Broker

- A separate `broker` container is the only component with access to the Docker
  socket; the bot, which runs plugin code, has none.
- It starts the sidecar containers plugins declare — unprivileged, memory
  capped, no published ports, no host mounts beyond the plugin's own files.
- It installs plugins, owns the trust configuration, and holds the AI and
  translation API keys, making those calls itself.

### Translation

- DeepL and Google Cloud are gone. Translation is keyless by default, and can be
  switched to the AI provider already configured for the bot — one credential
  instead of a second one to obtain and store for a job the model already does.

### Trust

- `config/` and `plugins/` are mounted read-only into the bot, so plugin code
  cannot mark its own source trusted or overwrite another plugin's files.
- A plugin from an untrusted source is refused sidecar containers.
- `.env` is no longer visible in the bot container.

### Migrated from the previous version

Existing settings move to their new homes on first start: per-plugin
namespaces, per-plugin databases, and the broker's credential store. Nothing
needs to be re-entered.

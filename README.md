# Doppler

Doppler is a self-hosted, open-source Discord bot with a web dashboard for configuration — no code editing or redeploys needed for day-to-day settings changes.

## Features

- 🎵 **Music** *(plugin)* — `/play` with queue support, playback controlled via on-message buttons (pause/resume, skip, stop, loop, queue). Runs on [Lavalink](https://github.com/lavalink-devs/Lavalink)/[wavelink](https://github.com/PythonistaGuild/Wavelink); multiple worker bot accounts can be added so several voice channels can play music at the same time.
- 🤖 **AI Chat** *(plugin)* — conversational AI; the persona name, system prompt, language and tone are the plugin's settings, while the provider (Google Gemini, DeepSeek, or ChatGPT) and its API key belong to the bot under **Settings → AI Provider**.
- 🌐 **Message Translation** *(plugin)* — right-click any message → Apps → Translate. Supports DeepL and Google (official API or a free keyless fallback).
- 🔊 **Temporary Voice Channels** *(plugin)* — joining a configured "hub" channel automatically creates a private voice channel for the user, with buttons to rename it, set a user limit, change the bitrate, lock it and allow specific people in.
- 🛡️ **Moderation** *(plugin)* — `/kick`, `/ban`, `/unban`, `/mute`, `/unmute`, `/warn`, with an optional mod-log channel and role-hierarchy checks.
- 🛠️ **Rich Embed Builder** *(plugin)* — build Discord messages visually in the dashboard using Components V2 (independent cards, each with its own accent color and ordered text/image blocks), then send them with `/embed <name>`. Images can be linked by URL or uploaded directly.
- 🔒 **Server Protect** *(plugin)* — optional raid/alt mitigation. Checks every new member's account age on join (DMs the reason and kicks if too new; grants a role automatically otherwise), and detects join bursts — react with an admin-gated alert or fully automatic lockdown (revokes invites, rejects new joins for a while).
- 🧠 **Plugins** — features can ship as self-contained plugins that are enabled, configured and reloaded from the dashboard. Reloading a plugin applies its new code *without restarting the bot*.
- 📊 **Web Dashboard** — live bot stats (uptime, host CPU/RAM, live-tailed logs), per-module enable/disable toggles, and settings management for every feature above.
- 🔐 **Dashboard Login** (optional) — gate the dashboard behind "Login with Discord"; only the home server's owner or an Administrator there gets in. It switches itself on once a home server is set and a Client Secret is saved in Settings — the Client ID is detected automatically, and the login page shows you the exact redirect URI to register (with a copy button and a direct link to your app's OAuth2 page).

**Doppler ships empty.** Every feature above is a plugin, installed from the dashboard's **Plugins → Browse** tab and then enabled, configured and reloaded from **Plugins → Installed**. The official plugins live on this repository's [`doppler/plugins`](../../tree/doppler/plugins) branch, which is configured as a trusted source out of the box.

## Plugins

A plugin is a self-contained folder holding a `plugin.json` manifest and its Python code. Built-in plugins ship in `dopplerbot/plugins/builtin/`; anything installed at runtime lands in `plugins/` at the repo root, which is bind-mounted and ignored by git, so installed plugins survive an image rebuild.

```
plugins/my_plugin/
├── plugin.json     # id, name, version, api_version, description, author, icon
└── plugin.py       # a subclass of dopplerbot.plugins.api.Plugin
```

Settings are key/value; a plugin that needs real tables gets its own SQLite
database at `savedata/plugins/<id>/data.db` through `ctx.db`, and creates its
schema itself. Nothing is shared with the core database or with other plugins.

```python
from dopplerbot.plugins.api import Plugin, PluginSetting, SettingType

class MyPlugin(Plugin):
    SETTINGS = (
        PluginSetting("api_key", SettingType.SECRET, label="API key"),
        PluginSetting("channel_id", SettingType.CHANNEL, default=0),
    )

    async def setup(self):
        await self.ctx.add_cog(MyCog(self))
```

A plugin declares its settings in code and the dashboard generates the form from that declaration — there is no dashboard code to write per plugin. Those settings are namespaced to the plugin's id, so two plugins can both use a key like `channel_id` without colliding, and a plugin reads and writes only its own keys: it has no path through this API to the bot token, the session secret, or another plugin's settings. Reading or writing a key the plugin didn't declare is an error, which turns a typo into a visible failure instead of a setting that silently never applies.

That last point is a namespace boundary, not a sandbox — a plugin is Python running in the bot's own process. **Installing a third-party plugin means running third-party code**, so only install plugins you trust.

Cogs and persistent views registered through `self.ctx` are removed automatically when the plugin is unloaded, which is what makes the dashboard's **Reload** button able to swap a plugin's code in place while the bot stays connected.

### Text generation

The AI provider and its API key are the bot's settings, not any plugin's. A
plugin asks for a completion:

```python
reply = await self.ctx.ai.complete(system_prompt, prompt)
```

and gets text back. It never learns the key, and does not know which service
answered — so one configured provider serves every plugin, and a plugin cannot
leak a credential it was never given (by logging its own settings, say).

Like the namespace boundary, this is a layer rather than a wall: plugin code
runs in the bot's process and could still go looking. It removes the *accident*,
not the *attack*.

### Sources and trust

Plugins are installed from *sources* — a GitHub repository and branch holding
one directory per plugin plus an `index.json` catalogue. `config/sources.json`
lists them:

```json
{
  "sources": [
    {
      "name": "doppler-official",
      "repo": "omka-1337/Doppler-DiscordBot",
      "branch": "doppler/plugins",
      "trusted": true
    }
  ]
}
```

A newly added source is **untrusted** until you say otherwise, and trust is not
decoration: the broker refuses to start sidecar containers for a plugin that
came from an untrusted source. A plugin that ships in `dopplerbot/plugins/builtin/`
counts as trusted, because it is part of the bot.

`config/` and `plugins/` are mounted **read-only into the bot container** and
writable only in the broker. That is what makes the flag mean anything: plugin
code runs inside the bot's process, so if it could write `sources.json` it
could mark its own source trusted, and if it could write `plugins/` it could
overwrite a trusted plugin's code. Both are enforced by the mount, not by a
check in the code — a plugin trying it gets `Read-only file system`.

### Sidecar containers

A plugin that needs a service of its own — the music plugin needs Lavalink —
declares it in its manifest:

```json
"services": [
  {
    "name": "lavalink",
    "image": "ghcr.io/lavalink-devs/lavalink:4",
    "port": 2333,
    "memory_mb": 700,
    "env_from_settings": { "LAVALINK_PASSWORD": "lavalink_password" },
    "files": { "lavalink.yml": "/opt/Lavalink/application.yml" }
  }
]
```

`await self.ctx.services.start("lavalink")` then brings it up and returns its
address. A separate `broker` container is the only part of the stack with
access to the Docker socket; **the bot deliberately has none**, because the bot
is where plugin code runs, and the Docker socket is equivalent to root on the
host.

The broker reads the manifests itself, from a read-only mount of the project,
and the bot can only name a service — never describe one. Everything about the
container comes from the manifest as the broker read it: the image (which must
pin a tag or digest), a memory cap, no published host ports, no capabilities,
`no-new-privileges`, and read-only file mounts that may only come from inside
the plugin's own folder. The one thing a plugin fills in is the *values* of
environment variables its manifest already declared under `env_from_settings`.

This bounds the damage; it does not make untrusted plugins safe. A plugin's
Python still runs inside the bot's process. What it buys is that "this plugin
needs a container" no longer means "this plugin gets root on the host".

**Single-guild by design.** All settings are global, not per-server, so Doppler is meant to run one bot instance per Discord server. It auto-locks to the first server it's added to (stored as `home_guild_id` under Settings → Main) and automatically leaves any other server it's invited to, to prevent two servers from silently sharing one config.

## Requirements

- Docker and Docker Compose
- A Discord bot application ([Discord Developer Portal](https://discord.com/developers/applications)) with the **Message Content** privileged intent enabled (required for AI chat and translation)
- Optional, depending on which modules you use:
  - An API key for whichever AI provider you pick for AI chat: [Gemini](https://aistudio.google.com/apikey), [DeepSeek](https://platform.deepseek.com/api_keys), or [OpenAI](https://platform.openai.com/api-keys)
  - A DeepL and/or Google Cloud Translate API key for translation (a free, keyless fallback is used otherwise)
  - For **Server Protect**: the **Server Members Intent** privileged intent (needed to detect joins at all)
  - For **Dashboard Login**: the OAuth2 Client Secret from the same Developer Portal application, plus each address you open the dashboard from registered under **OAuth2 → Redirects** (the login page shows the exact value to paste)

## Quick start (Docker)

```bash
git clone https://github.com/omka-1337/Doppler-DiscordBot.git
cd Doppler-DiscordBot
make start
```

`make start` creates `.env` from `.env.example` (with a random `LAVALINK_PASSWORD`) if one doesn't exist yet, then builds and starts all three containers (bot, web dashboard, Lavalink).

Once it's running:

1. Open `http://localhost:8000` (or `http://<your-server-address>:8000`).
2. Go to **Settings → API & System** and paste in your Discord bot token. Saving it restarts the bot container automatically.
3. Invite the bot to your server using the OAuth2 URL from the Discord Developer Portal (scopes: `bot`, `applications.commands`).

No `docker`/`docker compose` on the CLI required beyond the initial `make start` — everything else (modules, prefix, moderation, AI provider and key, translator provider, voice channel settings, embed templates, music worker bots) is managed from the dashboard.

### Without `make`

```bash
cp .env.example .env
# fill in LAVALINK_PASSWORD yourself, or leave it and set it later
docker compose up -d --build
```

## Configuration

| `.env` variable | Required | Notes |
|---|---|---|
| `DISCORD_BOT_TOKEN` | Yes | Can also be set later from the web dashboard |
| `LAVALINK_PASSWORD` | Yes | Must match `lavalink/application.yml`; auto-generated by `make start` |
| `YOUTUBE_OAUTH_REFRESH_TOKEN` | No | Optional, for YouTube playback; fill in via the dashboard's Music settings |
| `DASHBOARD_URL` | No | Public URL of this dashboard, used by the `/web` command's link. Leave empty to auto-detect the local IP instead |
| `DISCORD_CLIENT_SECRET` | Only for dashboard login | From the Developer Portal application's OAuth2 page. Can also be set from the dashboard |
| `SESSION_SECRET_KEY` | No | Generated and saved automatically on first run; don't set it yourself |

Everything else — module toggles, command prefix, AI provider/persona/prompt and API key, translator provider and keys, moderation and mod-log settings, temp-voice-channel IDs, music worker bot tokens, Server Protect's age/role/raid settings — lives in the SQLite database (`savedata/bot.db`) and is edited entirely through the web dashboard. Uploaded embed images are stored in `savedata/embeds/images/`.

## Common commands

```bash
make start     # first run / start the stack
make stop      # stop all containers
make restart   # restart all containers
make update    # git pull, rebuild, and restart
make status    # show container status
make logs      # tail all container logs (make logs s=bot for just one service)
```

## License

[GNU AGPL v3](LICENSE)

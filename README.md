# Doppler

Doppler is a self-hosted, open-source Discord bot with a web dashboard for configuration — no code editing or redeploys needed for day-to-day settings changes.

## Features

- 🎵 **Music** — `/play` with queue support, playback controlled via on-message buttons (pause/resume, skip, stop, loop, queue). Runs on [Lavalink](https://github.com/lavalink-devs/Lavalink)/[wavelink](https://github.com/PythonistaGuild/Wavelink); multiple worker bot accounts can be added so several voice channels can play music at the same time.
- 🤖 **AI Chat** *(plugin)* — conversational AI; pick a provider (Google Gemini, DeepSeek, or ChatGPT) from the dashboard, where the persona name, system prompt, language, tone, and provider API key are all configured.
- 🌐 **Message Translation** *(plugin)* — right-click any message → Apps → Translate. Supports DeepL and Google (official API or a free keyless fallback).
- 🔊 **Temporary Voice Channels** — joining a configured "hub" channel automatically creates a private voice channel for the user, with a rename button.
- 🛡️ **Moderation** *(plugin)* — `/kick`, `/ban`, `/unban`, `/mute`, `/unmute`, `/warn`, with an optional mod-log channel and role-hierarchy checks.
- 🛠️ **Rich Embed Builder** *(plugin)* — build Discord messages visually in the dashboard using Components V2 (independent cards, each with its own accent color and ordered text/image blocks), then send them with `/embed <name>`. Images can be linked by URL or uploaded directly.
- 🔒 **Server Protect** *(plugin)* — optional raid/alt mitigation. Checks every new member's account age on join (DMs the reason and kicks if too new; grants a role automatically otherwise), and detects join bursts — react with an admin-gated alert or fully automatic lockdown (revokes invites, rejects new joins for a while).
- 🧠 **Plugins** — features can ship as self-contained plugins that are enabled, configured and reloaded from the dashboard. Reloading a plugin applies its new code *without restarting the bot*.
- 📊 **Web Dashboard** — live bot stats (uptime, host CPU/RAM, live-tailed logs), per-module enable/disable toggles, and settings management for every feature above.
- 🔐 **Dashboard Login** (optional) — gate the dashboard behind "Login with Discord"; only the home server's owner or an Administrator there gets in. It switches itself on once a home server is set and a Client Secret is saved in Settings — the Client ID is detected automatically, and the login page shows you the exact redirect URI to register (with a copy button and a direct link to your app's OAuth2 page).

Anything marked *(plugin)* is enabled, configured and reloaded from the dashboard's **Plugins** tab; the rest are toggled from its **Modules** tab.

## Plugins

A plugin is a self-contained folder holding a `plugin.json` manifest and its Python code. Built-in plugins ship in `dopplerbot/plugins/builtin/`; anything installed at runtime lands in `plugins/` at the repo root, which is bind-mounted and ignored by git, so installed plugins survive an image rebuild.

```
plugins/my_plugin/
├── plugin.json     # id, name, version, api_version, description, author, icon
└── plugin.py       # a subclass of dopplerbot.plugins.api.Plugin
```

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

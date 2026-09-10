# Doppler

**Version 0.1.0** · [Changelog](CHANGELOG.md) · Plugin API 1.0

Doppler is a self-hosted, open-source Discord bot with a web dashboard for configuration — no code editing or redeploys needed for day-to-day settings changes.

## Features

- 🎵 **Music** *(plugin)* — `/play` with queue support, playback controlled via on-message buttons (pause/resume, skip, stop, loop, queue). Runs on [Lavalink](https://github.com/lavalink-devs/Lavalink)/[wavelink](https://github.com/PythonistaGuild/Wavelink); multiple worker bot accounts can be added so several voice channels can play music at the same time.
- 🤖 **AI Chat** *(plugin)* — conversational AI; the persona name, system prompt, language and tone are the plugin's settings, while the provider (Google Gemini, DeepSeek, or ChatGPT) and its API key belong to the bot under **Settings → AI Provider**.
- 🌐 **Message Translation** *(plugin)* — right-click any message → Apps → Translate. Free and keyless by default, or switch it to the AI provider you already configured for better idiom and context.
- 🔊 **Temporary Voice Channels** *(plugin)* — joining a configured "hub" channel automatically creates a private voice channel for the user, with buttons to rename it, set a user limit, change the bitrate, lock it and allow specific people in.
- 🛡️ **Moderation** *(plugin)* — `/kick`, `/ban`, `/unban`, `/mute`, `/unmute`, `/warn`, with an optional mod-log channel and role-hierarchy checks.
- 🛠️ **Rich Embed Builder** *(plugin)* — build Discord messages visually using Components V2: independent cards with text, images, thumbnails and link buttons, then send them with `/embed <name>`. The builder is the plugin's own page, rendered by the dashboard in a sandboxed frame.
- 🔒 **Server Protect** *(plugin)* — optional raid/alt mitigation. Checks every new member's account age on join (DMs the reason and kicks if too new; grants a role automatically otherwise), and detects join bursts — react with an admin-gated alert or fully automatic lockdown (revokes invites, rejects new joins for a while).
- 🧠 **Plugins** — every feature above is one. Install from a source, then enable, configure and reload from the dashboard; reloading applies a plugin's new code *without restarting the bot*.
- 📊 **Web Dashboard** — live bot stats (uptime, host CPU/RAM, live-tailed logs), a plugin browser for installing from a source, and generated settings forms for everything installed.
- 🔐 **Dashboard Login** — the dashboard is behind "Login with Discord"; only the home server's owner or an Administrator there gets in. It is set up during first run rather than being optional, so a fresh install is never briefly open. The Client ID is detected automatically, and both the setup and login pages show the exact redirect URI to register.

**Doppler ships empty.** Every feature above is a plugin, installed from the dashboard's **Plugins → Browse** tab and then enabled, configured and reloaded from **Plugins → Installed**. The official plugins live on this repository's [`doppler/plugins`](../../tree/doppler/plugins) branch, which is configured as a trusted source out of the box.

## Plugins

A plugin is a self-contained folder holding a `plugin.json` manifest and its Python code. Installed plugins land in `plugins/` at the repo root, which the broker writes, the bot only reads, and git ignores — so they survive an image rebuild and never end up in your commits.

```
plugins/my_plugin/          # installed plugins; the broker writes this
├── plugin.json             # id, name, version, api_version, description, icon
└── plugin.py               # a subclass of dopplerbot.plugins.api.Plugin
```

(`dopplerbot/plugins/` is the plugin *system* — the loader, the manifest parser
and the `api` module plugins import. No plugin lives there.)

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

### Provider credentials

The AI provider and its key are configured once, under **Settings → AI
Provider**, and shared by every plugin that uses a model — so a key is never
pasted into more than one place, and switching model is one change rather than
one per plugin. Translation needs no key of its own: it is keyless by default,
and a plugin that offers the choice can point it at the same AI provider.

They are held by the **broker**, in a `secrets/` volume that is not mounted into
the bot container at all, and the broker never hands a value back. A plugin asks
for the result:

```python
reply  = await self.ctx.ai.complete(system_prompt, prompt)
result = await self.ctx.translate.text("hello", "uk")
```

The call is made on the broker's side, so the credential never enters the
process plugin code runs in. That is a real boundary, unlike the settings
namespacing, which is a convention: a plugin can read the bot's database
directly if it wants to.

**What is still reachable from a plugin**, and cannot be moved without a much
larger redesign:

- `DISCORD_BOT_TOKEN` — discord.py holds it in memory to keep the gateway open.
  A plugin can read it, and with it do anything the bot can do. This is the
  hard floor of running plugins in the bot's process.
- The music plugin's Lavalink password and YouTube refresh token, because
  `wavelink` connects from the bot's process.

So installing a plugin still means trusting it. What this buys is that the
provider keys are no longer part of what you hand over.

### Sources and trust

Plugins are installed from *sources* — a GitHub repository and branch holding
one directory per plugin plus an `index.json` catalogue. There is exactly one
place plugins live, `plugins/`, and only the broker writes it. `config/sources.json`
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
came from an untrusted source. Only a plugin the broker itself installed from a
currently-trusted source qualifies — a directory dropped into `plugins/` by hand
still loads and runs, but gets no containers, because there is no record of
where it came from.

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
- A Discord bot application ([Discord Developer Portal](https://discord.com/developers/applications)) with the **Message Content** privileged intent enabled (AI chat reads messages from the gateway)
- The OAuth2 **Client Secret** from the same application, and each address you open the dashboard from registered under **OAuth2 → Redirects**. Both are needed to finish first-run setup.
- Optional, depending on which plugins you install:
  - An API key for whichever AI provider you pick: [Gemini](https://aistudio.google.com/apikey), [DeepSeek](https://platform.deepseek.com/api_keys), or [OpenAI](https://platform.openai.com/api-keys). AI chat needs one; translation can use it instead of the keyless backend.
  - For **Server Protect**: the **Server Members Intent** privileged intent (needed to detect joins at all)

## Quick start (Docker)

```bash
git clone https://github.com/omka-1337/Doppler-DiscordBot.git
cd Doppler-DiscordBot
make start
```

`make start` creates `.env` from `.env.example` (with a random `LAVALINK_PASSWORD`) if one doesn't exist yet, then builds and starts the three containers: the bot, the web dashboard, and the broker. Lavalink is not among them — the broker starts it when the music plugin asks for it.

Once it's running:

1. Open `http://localhost:8000` (or `http://<your-server-address>:8000`). Everything
   redirects to a first-run setup page until the bot is configured.
2. Paste your **bot token** and **OAuth2 client secret**. Both are verified against
   Discord before they can be saved, and the page shows the redirect URI you need to
   register under **OAuth2 → Redirects**.
3. Saving takes you to the Discord login. The bot container picks up the token on its
   own — no manual restart.
4. Invite the bot to your server using the OAuth2 URL from the Developer Portal
   (scopes: `bot`, `applications.commands`). The first server it joins becomes its home.

The client secret is required rather than optional: dashboard login is set up before
the dashboard is ever reachable, so a fresh install is never briefly open.

No `docker`/`docker compose` on the CLI required beyond the initial `make start` — everything else (installing and enabling plugins, their settings, the AI provider and key, embed templates, music worker bots) is managed from the dashboard.

### Without `make`

```bash
cp .env.example .env
# fill in LAVALINK_PASSWORD yourself, or leave it and set it later
docker compose up -d --build
```

## Configuration

| `.env` variable | Required | Notes |
|---|---|---|
| `DISCORD_BOT_TOKEN` | Yes | Normally entered during first-run setup rather than by hand |
| `GEMINI_API_KEY` | No | Seeded into the broker's credential store on first run; after that the dashboard owns it |
| `LAVALINK_PASSWORD` | For music | Auto-generated by `make start`, then seeded into the music plugin's settings, which is what the Lavalink container is started with |
| `YOUTUBE_OAUTH_REFRESH_TOKEN` | No | Optional, for YouTube playback; fill in via the dashboard's Music settings |
| `DISCORD_CLIENT_SECRET` | Yes | From the Developer Portal application's OAuth2 page. Normally entered during first-run setup rather than by hand |
| `SESSION_SECRET_KEY` | No | Generated and saved automatically on first run; don't set it yourself |

Everything else — which plugins are installed and enabled, their settings, the AI provider and its key, music worker bot tokens — lives in the SQLite database (`savedata/bot.db`) and the broker's store, and is edited entirely through the web dashboard. Embed templates and their uploaded images are stored in `savedata/embeds/`.

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

# builtin/

Plugins bundled with the bot itself. Doppler ships empty: the official plugins
live on the `doppler/plugins` branch and are installed from the dashboard's
**Plugins → Browse** tab.

Anything dropped in here is loaded like any installed plugin, but is treated as
trusted without being recorded in `config/installed.json` — it is part of the
bot, as trusted as the bot's own code. Use it for a plugin you wrote and ship
yourself, not for third-party code.

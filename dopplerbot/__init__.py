"""Doppler — a self-hosted Discord bot assembled from plugins."""

# The bot's own version. Separate from the plugin API version in
# dopplerbot/plugins/manifest.py: a plugin declares which *API* it was written
# against, and that contract changes far less often than the bot around it.
__version__ = "0.2.0"

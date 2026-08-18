import discord

class MusicControlView(discord.ui.View):

    """
    Buttons below the "Now playing" embed. Handled by the same discord.Client
    (worker) that sent the message—Discord sends the interaction to
    the bot that sent the message with the buttons, so View doesn't need to
    determine "which bot owns it" here, unlike text commands in
    MusicCommands.py, where such a lookup is explicitly required.
    """

    def __init__(self, player):
        # The `timeout=None` setting ensures that the buttons remain active for the entire
        # duration of the message, preventing them from automatically turning off after the standard 180 seconds of inactivity.
        super().__init__(timeout=None)
        self.player = player

    @discord.ui.button(label="⏸️ Pause", style=discord.ButtonStyle.secondary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.player.paused:
            await self.player.pause(False)
            button.label = "⏸️ Pause"
        else:
            await self.player.pause(True)
            button.label = "▶️ Resume"

        # edit_message: both confirms the interaction (Discord requires
        # a response within a few seconds; otherwise, the user sees "Interaction
        # failed") and updates the button text on the message itself.
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        # defer(), not edit_message(): this message is deleted anyway
        # and resent via play_next() (through on_wavelink_track_end),
        # so here we're simply acknowledging the click without any visible action.
        await interaction.response.defer()

        # current_track = None BEFORE skip(): if Loop is enabled, play_next()
        # (which runs when the track ends) checks current_track and
        # would repeat the skipped track again instead of moving on to the next one in the queue.
        self.player.current_track = None

        # skip(force=True) generates the on_wavelink_track_end event on its own—the same
        # transition mechanism as when a track ends naturally.
        await self.player.skip(force=True)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.player.queue.clear()
        # cleanup_and_disconnect removes the now_playing_message itself and exits
        # the voice channel—the same centralized approach as with an inactivity
        # timeout and when the channel is empty.
        await self.player.cleanup_and_disconnect()

    @discord.ui.button(label="🔁 Loop", style=discord.ButtonStyle.secondary)
    async def toggle_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.loop = not self.player.loop
        button.style = discord.ButtonStyle.success if self.player.loop else discord.ButtonStyle.secondary

        await interaction.response.edit_message(view=self)
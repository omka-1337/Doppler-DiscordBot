# secrets/

Provider credentials — AI and translation API keys.

This directory is mounted **only into the broker**. It is not visible in the
bot container at all, which is the point: plugin code runs inside the bot's
process, so anything reachable from there is reachable by a plugin.

The broker never hands these values back out. It uses them to make the call
itself and returns only the result, so a plugin can ask for a translation or a
completion without the key ever entering the process it runs in.

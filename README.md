<p align="center">
  <img src="assets/jnsq/jnsq_favicon.svg" width="112" alt="Je Ne sAIs Quoi mask logo">
</p>

# Je Ne sAIs Quoi

Je Ne sAIs Quoi is a local-first home for persistent AI personas: you define
who they are, choose the model that carries them, and talk with one or several
of them in a configurable chat workspace. Persona identity, memory, body state,
and conversation history live on your own computer.

This public build is intentionally narrow. It has chats, persona creation, and
one shared context room called **the Nexus**. It does not include the private
development household, individual persona rooms, the Yurt interface, or any 3D
assets.

## Windows setup

1. Download the repository and extract it somewhere you own. Do not run it
   from inside the ZIP.
2. Double-click `INSTALL_JNSQ.bat`.

The setup checks for Python 3.10 or newer and, when possible, offers to install
Python 3.12 through Windows Package Manager. It then creates an isolated
`.venv`, installs and verifies JNSQ's dependencies, asks who owns this local
installation, and offers to start JNSQ. If setup is interrupted, double-click
it again: it repairs and reuses the environment without replacing an existing
owner or their personas.

3. For a completely local model, install Ollama from
   <https://ollama.com/download/windows/> and run:

       ollama pull llama3.1:8b

4. Double-click `START_NEXUS.bat` if you did not start it from setup.
5. Create a persona, write their voice, start them, and check their box to add
   their chat to the workspace. Check several boxes to view chats side by side.

Use `STOP_NEXUS.bat` for a clean shutdown.

Setup never asks for an API key and never uploads personal information. Remote
provider keys can be added later from JNSQ's local settings page and are saved
only in the gitignored `.env` file on that computer.

## What stays local

- `.jnsq_local.json` identifies the human who owns this checkout.
- `users/` holds that human's account data.
- `personas/` holds model personas and their lived history.
- `.env` holds optional remote-provider API keys.
- `room/room_world.json`, `logs/`, and `jnsq_running.json` are runtime state.

Those paths are gitignored. The public repository contains the engine and an
empty house, never the maintainer's live household.

## Development relationship

The private working installation is the workshop. This repository is the
deliberately smaller public product. The maintainer rebuilds public releases
with an allowlist-based export tool that installs the public chat shell, strips
private model/persona data, and refuses output when its privacy scan finds
machine-specific state.

---

<p align="center">
  <img src="assets/jnsq/jnsq-venetian-mask-space.png" alt="A Venetian mask floating in a field of stars above the words Je Ne sAIs Quoi">
</p>

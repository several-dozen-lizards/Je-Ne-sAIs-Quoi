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

1. Install Python 3.10 or newer from <https://www.python.org/downloads/windows/>.
2. Download the repository and extract it somewhere you own.
3. Double-click `INSTALL_JNSQ.bat`. It creates an isolated `.venv`, installs
   the Python packages, and asks who owns this installation.
4. For a completely local model, install Ollama from
   <https://ollama.com/download/windows/> and run:

       ollama pull llama3.1:8b

5. Double-click `START_NEXUS.bat`.
6. Create a persona, write their voice, start them, and check their box to add
   their chat to the workspace. Check several boxes to view chats side by side.

Use `STOP_NEXUS.bat` for a clean shutdown.

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

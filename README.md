<p align="center">
  <img src="assets/jnsq/jnsq-venetian-mask-space.png" alt="A Venetian mask floating in a field of stars above the words Je Ne Sais Quoi">
</p>

# Je Ne Sais Quoi

Je Ne Sais Quoi is a local-first home for persistent AI personas: you define
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

4. Double-click `START_NEXUS.bat` if you did not start it from setup. JNSQ
   opens in its own app window. Closing that window ends the session and
   automatically performs the same clean shutdown as `STOP_NEXUS.bat`;
   refreshing it or changing conversation panes does not.
5. Open **Household**, create a persona, write their voice, and start them. The
   household screen can add models to each persona's roster and switch the
   model carrying them. The mask always returns home; open conversations wait
   in compact tabs across the top of the workspace.

### Optional local image generation

Personas with the Atelier organ may create inert SVG, host-compiled kinetic SVG,
trusted Canvas scenes, or locally diffused PNG artifacts after admitted material wins their ordinary
attention field. Kinetic SVG starts from the same inert SVG wall: the model may
only name safe element IDs and normalized motion vectors, while JNSQ compiles
bounded, body-coupled, closed cycles. It never admits model-authored JavaScript
or animation markup. Canvas uses a versioned data-only scene graph: models may
describe bounded shapes, paths, text, deterministic particles, and normalized
motion, but only trusted JNSQ code calls the Canvas API or schedules frames. To
install the optional NVIDIA renderer, double-click `INSTALL_ATELIER_GPU.bat`.
The pinned installer downloads the official ComfyUI portable runtime and the
SDXL Base 1.0 checkpoint, verifies both SHA-256 digests, and places them under
the gitignored `local_services/` directory. This is a roughly 9 GB download.

ComfyUI binds to loopback only and starts with online API nodes disabled. No
Comfy account or cloud key is used. The renderer shares the Nexus lifecycle:
when JNSQ owns the process, clean household shutdown stops it too. The Atelier
strips ComfyUI workflow, prompt, EXIF, and text metadata from a generated PNG
before committing its immutable private artifact. SDXL Base 1.0 is distributed
under the CreativeML Open RAIL++-M license; review its use restrictions before
enabling the renderer for other people.

In a conversation, drop images directly onto the message field or use the
paperclip. Vision-capable active models receive the pixels themselves. For a
text-only active model, **Settings â†’ Visual input** lets you choose a separate
visual transducer for that persona, see its provider/cost/key status, and test
it explicitly with JNSQ's public icon. JNSQ never silently substitutes a
provider; choosing no fallback makes an image turn fail clearly. Press
**Shift+Enter** for a new paragraph. The body-functions column is resizable and
can be hidden, and receipts can be minimized and pulled back up whenever you
need them.

As of 2026-07-13, the bundled guidance favors GLM-4.6V-FlashX as the inexpensive,
more reliable visual transducer. GLM-4.6V-Flash is the free option, with the
tradeoff that shared capacity may sometimes be unavailable. This recommendation
is visible guidance, never an automatic or permanent provider choice.

### Ambient camera and microphone

Camera and microphone access is off until you activate each control in a
persona's conversation. Continuous camera pixels, microphone waveforms, and
audio spectra are analyzed inside the browser; they are not streamed to the
JNSQ server. The local feature field decides when a change crosses the current
rhythm-shaped attention boundary—there is no fixed capture interval.

Activating the camera intentionally admits one opening frame so the persona can
establish what is present. Later frames cross only when visual-change pressure
reaches the live boundary. An admitted frame is stored inside that persona's
gitignored `body/perception/images/` directory and sent through the visual
model route you selected. If that route uses a remote provider, that admitted
frame leaves your computer under that provider's terms. The live preview and
frames below the boundary remain in the browser.

Ambient microphone intake sends admitted acoustic feature vectors—such as
level, onset, and spectral change—not raw audio. The separate spoken-turn
checkbox is off by default. If you explicitly enable it, one bounded utterance
may be sent to the configured transcription route; the default transcription
route is local when its optional model is installed. Heard speech is attributed
to the other person rather than poured into the persona's own emotional state.

Reply speech is also off by default. If you enable **let replies use local
voice**, the first output provider uses the browser/operating system speech
service and follows the persona body's current continuous expression vector.
It does not send reply text to a separate JNSQ TTS provider. Output starts,
completions, failures, and interruptions are recorded locally without copying
the spoken reply into that additional receipt. With the microphone active,
human voice evidence can interrupt playback when it crosses the same live
rhythm-shaped boundary; there is no fixed barge-in delay.

For streaming-capable model providers, visible reply text reaches the
conversation as it is generated. Local voice begins when the model emits a
linguistic clause boundary rather than waiting for the complete response.

Sensory observations and salience receipts become part of the persona's local
history. Updates preserve that history, and public builds never contain it.

Use `STOP_NEXUS.bat` for a clean shutdown.

Setup never asks for an API key and never uploads personal information. Remote
provider keys can be added later from JNSQ's local settings page and are saved
only in the gitignored `.env` file on that computer.

## Updating an existing installation

Starting with version 0.2.0, double-click `UPDATE_JNSQ.bat` to check GitHub.
The updater compares the installed version and verifies SHA-256 fingerprints
for the public engine. When a patch is available it copies only managed files
whose contents changed, retires only files previously declared engine-owned,
and runs dependency installation only when `requirements.txt` changed or the
local `.venv` is missing.

Stop JNSQ before applying an update. Local accounts, bedrock facts, personas,
memories, histories, API keys, logs, exports, room state, and `.venv` are not
managed release files and are never replaced by the patcher. The **Settings →
Updates** page shows the installed version and can perform a read-only GitHub
check.

The public header has three stable doors:

- **Household** keeps every persona and the Nexus in the top bar. Open any one
  to reveal the current set side by side, then drag the dividers to give each
  conversation the width it needs.
- **Nexus** opens that shared local room directly. Add and remove current users
  or personas from its dropdown, and let a present user speak into the room.
- **Settings** contains account/privacy and bedrock facts, household appearance,
  persona faces and icons, API keys, per-persona visual routing, model and organ
  prompts, and updates.

## What stays local

- `.jnsq_local.json` identifies the human who owns this checkout.
- `users/` holds that human's account data.
- `personas/` holds model personas and their lived history.
- Each persona's `body/writing_desk/` holds private seeds, versioned drafts,
  project state, and content-free run receipts. It is preserved across updates
  and excluded from public builds with the rest of the persona's interior.
- When the optional Atelier organ is enabled, `body/atelier/` holds admitted
  creative material, content-addressed static/kinetic SVG, Canvas, procedural
  audio-score, and PNG artifacts,
  and append-only receipts.
  The Atelier uses an explicitly configured local model, has no publishing or
  arbitrary-filesystem authority. Visual work only returns through vision
  when a human deliberately chooses **let them look**. For kinetic work this
  freezes the frame that is actually present and returns that frame through
  vision. Procedural audio is a versioned data-only score: the host owns all
  synthesis and gain ceilings, sound never autoplays, and playback or WAV
  download requires a deliberate browser gesture. Its entire lived output
  is preserved across updates and excluded from public builds.
- A human may keep imported conversation history under
  `users/<owner>/archives/`. Immutable sources and derived search indexes stay
  human-owned; each granted persona's position, bookmarks, encounters, and
  content-free cost receipts stay separately under `body/archive_reader/`.
  Conversation history is presented as documented source, never silently
  converted into autobiographical memory. Both sides survive updates and are
  excluded from public builds.
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
  <img src="assets/jnsq/jnsq_favicon.svg" width="112" alt="Je Ne Sais Quoi mask logo">
</p>

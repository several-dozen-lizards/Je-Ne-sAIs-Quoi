# JNAIQ 0.12.2 preview 2

A small, opt-in test drive of the public app and its new JNAIQ-themed Builders
and Worlds interface. This is a prerelease, not a completed 3D builders release.

## Install and explore

Download **JNAIQ-0.12.2-preview.2.zip** from this release's Assets, extract into a
new folder, and run **INSTALL_JNAIQ.bat** on Windows. Follow the setup prompts;
use **START_NEXUS.bat** for later launches and **STOP_NEXUS.bat** to stop it.
Python and package downloads are required. See the included README and setup
guide for model/provider setup. Cloud model use requires your own credentials
and may incur charges; model replies were not exercised in this release check.

Please use a fresh installation for this test. Keep existing installations and
saved data separate. The normal updater still follows the stable main branch;
it will not install this prerelease. macOS has not been validated for this cut.

## What to try

- Initial setup, navigation, settings, and ordinary main-app workflows.
- The new Builders and Worlds pages, their availability messages, and theme.
- The Builders introduction: step through it, turn it off, and reopen help.
- Readability at different window sizes and with your preferred theme/font.

## What is still pending

The optional Avatar Creator / World Builder download is **not available in this
release**. The main package contains no 3D asset packs or compatible household
3D runtime. The Worlds page will report the unavailable runtime. Connecting an
existing compatible standalone editor is an advanced path, not a supplied or
end-to-end validated installation. Do not expect this package alone to create,
render, assign, import, or edit 3D avatars and worlds.

The refreshed standalone editor guides, save/reopen workflows, asset admission,
and end-to-end 3D checks remain work in progress. Unverified assets are not
included. No private household residents, conversations, or API keys ship here.

## Feedback

Tell us your OS, what you tried, what you expected, and what happened. Screenshots
help; remove API keys, personal conversations, and other private information.
Use GitHub Issues or the Discord conversation where you received this link.

Validation: clean Windows dependency setup and isolated empty-household browser
launch; main package smoke and managed-file/privacy checks. These checks do not
establish model-provider inference or complete 3D workflow acceptance.

## Experimental VR preference (preview 2)

Settings → Household appearance and the Worlds page now include an experimental
VR switch, off by default. The notice explains that VR is a work in progress,
untested across headsets, and likely to be slow, clunky, or fail to connect.
The choice persists in this installation. Enabling it permits headset access
in newly opened embedded Worlds views; it does not start a headset session.
Disabling it closes an embedded view. Directly opened renderer windows have
their own headset controls and must be closed separately.

**The required 3D runtime is still absent from this download. This switch does
not make VR usable with this package alone.** There is no new headset testing
or completed VR support claim in preview 2. Existing compatible runtime users
can opt in and try their renderer's HEADSET control; that route remains
experimental. No private household renderer or unverified asset pack is included.

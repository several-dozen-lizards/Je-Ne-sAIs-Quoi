# JNAIQ 0.12.6 — getting started and testing notes

Download JNAIQ-0.12.6.zip from the release Assets, extract into a new folder,
and run INSTALL_JNAIQ.bat on Windows. Use START_NEXUS.bat for later launches
and STOP_NEXUS.bat to stop this installation. Follow the README for provider
setup. Cloud providers require your credentials and may incur charges.
Existing public installations can use UPDATE_JNAIQ.bat; back up the entire
installation folder first. The updater preserves local saved work.

## Optional avatars and worlds

Open Builders in JNAIQ to find the separate curated Builders download and
connect to its local server. The getting-started guide can be turned off and
reopened. Save your original avatar/world designs in Builders for later edits.

Export an avatar GLB and import it in JNAIQ's Worlds page. Select a household
member and Apply avatar; Restore previous reverses the assignment.

For 3D worlds, install Node.js and run INSTALL_3D_RUNTIME.bat in this JNAIQ
folder. About 641 MB of verified archives are downloaded; only the admitted
landscape maps and six furniture objects are installed. No unfinished models,
private creations, or assets with unverified redistribution terms are bundled.

Export world JSON from World Builder, then Import and publish world in Worlds.
Travel here moves your local user; opening a view alone does not move anyone.
Use the visitor Travel menu to move between worlds or Return to Nexus.
Edit the saved original in Builders and import again using Update for a
same-named world. Leave an occupied world before replacing it. Avatar edits
are imported as new entries and can then be assigned.

## Experimental VR and known limits

VR is off by default. Enable Experimental VR in Worlds and use Headset in a
published world. Physical-headset behavior is untested and likely clunky;
this remains work in progress. Original procedural walking and 22 expressive motions are included for compatible
humanoid rigs. Unverified third-party animation packs remain excluded. The original Nexus uses its
ordinary room view. macOS remains unqualified. GPT-4.1 movement choice on request is verified below;
other provider behavior is unqualified.

Smoke/privacy, optional installation and modified-file preservation, avatar
assignment/restore, world updates, travel, restart persistence, stale-request
rejection and updater rollback were checked on isolated copies. The original pose integration was qualified with synthetic AI action outputs and
actual exported starter-rig checks; the 0.12.6 real conversation check is below.
This this does not claim every provider will
choose a pose or that every imported skeleton is compatible.
Please report reproduction steps and sanitized errors; do not post credentials,
private conversations, or your whole saved household folder.


## 0.12.5 fresh-install conversation check

Fresh released installer and optional tools, a new synthetic persona, and real
OpenAI GPT-4.1 were used in an isolated installation. Startup and canonical room
recovery passed. On a request to demonstrate a movement of its own choosing,
the AI selected talk_gesture; the host recorded it and the browser animated the
28-joint curated avatar without renderer errors. An ordinary conversation turn
selected no body action. No action tags or named pose were supplied by the tester.
An earlier nonstreaming request timed out; successful checks used normal streaming.
This does not qualify spontaneous pose frequency, every provider/rig, or VR hardware.


## Ordinary conversational pose qualification

Current posture and held gestures now remain in canonical room context even
when old events expire. Basic body-action tags come before long scenery lists.
Floor sitting/lying help matches supported actions, and ordinary-chat availability
is explicit while speaking without any action stays equally valid.

A fresh GPT-4.1 persona completed the same eight ordinary conversation inputs as
the unchanged 0.12.5 baseline. Both samples selected zero body actions. These fixes
repair context gaps; they do not establish spontaneous conversational posing.
The earlier explicitly requested AI-selected motion remains verified. Other
providers, broad rig compatibility and physical VR remain unqualified.

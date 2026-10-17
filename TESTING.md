# JNAIQ 0.12.4 — getting started and testing notes

Download JNAIQ-0.12.4.zip from the release Assets, extract into a new folder,
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
ordinary room view. macOS and model replies were not qualified for this cut.

Smoke/privacy, optional installation and modified-file preservation, avatar
assignment/restore, world updates, travel, restart persistence, stale-request
rejection and updater rollback were checked on isolated copies. The public pose integration is qualified with synthetic AI action outputs and
actual exported starter-rig checks; this does not claim every provider will
choose a pose or that every imported skeleton is compatible.
Please report reproduction steps and sanitized errors; do not post credentials,
private conversations, or your whole saved household folder.

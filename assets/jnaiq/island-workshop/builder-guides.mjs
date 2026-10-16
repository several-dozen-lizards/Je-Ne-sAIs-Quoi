import {installGuide} from './getting-started.mjs';
export function avatarGuide(){return installGuide({id:'avatar',title:'Your first avatar',parent:document.querySelector('main'),before:document.getElementById('studioSetup'),savedEvent:'jnaiq-avatar-saved',steps:[
 {title:'Choose a starting point',text:'Choose a Starting model and let its preview load. Some models have fixed shapes; use the features that model supports. If the library is empty, a compatible model must be installed first.',selector:'#studioCandidate'},
 {title:'Make it yours',text:'Use Body and Face to change shape, and the appearance controls for available skin, hair and clothes. Try expressions is only a preview. Undo lets you back up without starting over.',selector:'#studioEditTitle'},
 {title:'Name and save',text:'Give the design a name, then choose Save design. Wait for the saved confirmation. This guide turns off after a successful save; a failed save keeps it available. Saving a draft does not assign it to a household member.',selector:'#builderName'},
 {title:'Return whenever you like',text:'Use Edit saved avatar or Saved design to reopen your work. Save design adds a revision to that design; Save as new design makes a separate variation. Download 3D avatar exports a copy. Reopen this Help section at any time.',selector:'#builderRecipe'}
]});}
export function worldGuide(){return installGuide({id:'world',title:'Your first world',parent:document.body,before:document.querySelector('main'),savedEvent:'jnaiq-world-saved',steps:[
 {title:'Start with a landscape',text:'Explore the island already in the editor, or choose New for a different starting point. Drag to look around and scroll to zoom. New offers a chance to preserve your current draft before starting another.',selector:'#newIsland'},
 {title:'Shape a place',text:'Try a terrain brush, then add scenery or a building from the editor panels. Use Undo to try another direction. You can leave a world simple and add more later.',selector:'#undo'},
 {title:'Name and save',text:'Give the island a name and choose Save island. Wait for the saved confirmation. A successful save turns this guide off automatically. If saving fails, keep the tab open; Export preserves a portable copy.',selector:'#save'},
 {title:'Keep building later',text:'Edit saved world opens My islands. Choose Edit beside your world, make changes, then Save island. Save a copy makes a separate variation. A saved draft is separate from a household destination; publishing or updating one requires a compatible household runtime.',selector:'#library'}
]});}

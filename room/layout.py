"""Neutral seed world used only in privacy-clean starter distributions."""
from room.state import Room, RoomObject


def build_persona_den(persona: str, display_name: str = None) -> Room:
    owner = persona.strip().lower()
    display = (display_name or owner.replace("_", " ").title()).strip()
    den = Room(f"{owner}_den", f"{display}'s Den", 2.5,
               f"A private room belonging to {display}. It begins spare; "
               "what enters it can become part of its history.")
    desk_id = f"{owner}_desk"
    den.objects = {desk_id: RoomObject(
        desk_id, f"{display}'s writing desk", [1.5, -1.5],
        mass_kg=25.0, capability="private_writing", owner=owner,
        affordances={"focus": 0.7, "reflect": 0.8},
        texture="unfinished wood", kind="desk", size_m=1.2,
        description=f"Private. What {display} writes here is theirs.")}
    return den


def build_world() -> dict:
    nexus = Room("nexus", "the Nexus", 4.0,
                 "The commons. Where this household can cross paths.")
    nexus.objects = {o.id: o for o in [
        RoomObject("public_desk", "the commons writing desk", [2.0, -3.0],
                   mass_kg=30.0, capability="writing",
                   affordances={"share": 0.8, "focus": 0.6},
                   texture="smooth pine", kind="desk", size_m=1.4,
                   description="Pages written here remain available to "
                               "anyone who can enter the commons."),
        RoomObject("commons_couch", "the commons couch", [-1.5, 2.0],
                   mass_kg=55.0,
                   affordances={"rest": 0.8, "company": 0.8},
                   texture="soft fabric", kind="couch", size_m=2.2,
                   description="A shared place to sit."),
    ]}
    return {"rooms": {"nexus": nexus}, "adjacency": {"nexus": []}}

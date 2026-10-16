"""Live teleporter directory and grounded arrival points; no renderer owns routing."""
from room.state import heading_toward


def directory(app):
    app.state.world_destinations.sync()
    entries = []
    for rid, room in app.state.rooms.items():
        for oid, gate in room.objects.items():
            if gate.capability != 'portal':
                continue
            world_name = 'Nexus / Yurt' if rid == 'nexus' else room.name
            entries.append({'destination': rid + '/' + oid, 'room': rid,
                            'portal': oid, 'name': f'{world_name} — {gate.name}',
                            'world_name': world_name, 'portal_name': gate.name,
                            'scene': room.scene, 'owner': room.owner})
    return entries


def destinations(app, room_id, member, source=None):
    entries = directory(app)
    room = app.state.rooms.get(room_id)
    near = room.portals_near(member) if room else []
    source = source or (near[0] if near else None)
    return [entry for entry in entries
            if not (entry['room'] == room_id and entry['portal'] == source)]


def resolve(app, target):
    matches = [entry for entry in directory(app)
               if entry['destination'] == target or entry['room'] == target]
    if not matches:
        raise ValueError('That teleporter is no longer available. Open the destination list again.')
    # Legacy room-only choices retain a deterministic entrance. New menus
    # always carry the exact destination key, including multiple gates/world.
    return matches[0]


def landing(room, portal, member):
    gate = room.objects.get(portal)
    if gate is None or gate.capability != 'portal':
        raise ValueError('The destination teleporter was removed.')
    # Authored door rooms already publish a body-safe point on the interior
    # side of their entrance.  The portal object itself sits in the door
    # plane, which is correct for reach/focus but wrong for a body landing.
    # Only couple a door to that arrival when it is physically the matching
    # entrance; added gates and freestanding teleporters keep their own spot.
    arrival = getattr(room, 'arrival_m', None)
    door_arrival = (portal.endswith('door') and arrival is not None
                    and room._dist(gate.position_m, arrival)
                    <= max(1.5, float(getattr(gate, 'size_m', 0.6))))
    anchor = arrival if door_arrival else gate.position_m
    position = room._deconflict(room._clamp_inside(anchor), member)
    height = 0.0
    if getattr(room, 'navigation', None):
        height = room.navigation.support(position[0], -position[1], room.object_elevation(portal))
        if height is None or not room.navigation.clear(position[0], height, -position[1]):
            raise ValueError('The destination teleporter has no clear supported arrival space. Move it in the world builder.')
    heading = (room.arrival_heading_deg if door_arrival
               and room.arrival_heading_deg is not None
               else heading_toward(position, [0, 0])
               if portal.endswith('door') else gate.rot_deg)
    return position, height, heading

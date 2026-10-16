"""Published local avatar packages and reversible, versioned assignments.

Candidate staging stays read-only with respect to residents. Publication makes
an immutable package; assignment is a separate explicit operation. Imported and
designer-produced GLBs use this identical path.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import threading
import uuid
from pathlib import Path
from core.body_packages import BodyPackageError, _read_glb_json
from core.body_candidates import load_candidate, candidate_model_path, save_candidate_mapping
from core.body_recipes import _atomic_json, _now

_LOCK = threading.RLock()

def _id(value):
    if not re.fullmatch(r'[a-f0-9]{32}', str(value)):
        raise BodyPackageError('Invalid avatar package id')
    return str(value)

def load_package(root, package_id):
    path = Path(root) / 'packages' / (_id(package_id) + '.json')
    if not path.is_file():
        raise BodyPackageError('Avatar package not found')
    return json.loads(path.read_text(encoding='utf-8'))

def list_packages(root):
    return sorted([json.loads(p.read_text(encoding='utf-8'))
                   for p in (Path(root) / 'packages').glob('*.json')],
                  key=lambda r: r['created_at'], reverse=True)

def publish(root, candidates, candidate_id, name, mapping_source=None):
    record = load_candidate(candidates, _id(candidate_id), 'starter_persona')
    path = candidate_model_path(candidates, candidate_id, 'starter_persona')
    # Only self-contained models. Never let a model trigger remote texture or
    # buffer requests when assigned in a resident's room.
    model, _, _ = _read_glb_json(path)
    for entry in model.get('buffers', []) + model.get('images', []):
        if entry.get('uri') and not entry['uri'].startswith('data:'):
            raise BodyPackageError('Embed all textures and buffers before publishing')
    adapter = record.get('adapter')
    if mapping_source:
        source = load_candidate(candidates, _id(mapping_source), 'starter_persona')
        source_model, _, _ = _read_glb_json(candidate_model_path(candidates, mapping_source, 'starter_persona'))
        # Preview derivation appends fitted brows/lashes. Original node indices
        # and names, and every skin's joint indices, must still match before
        # inheriting the mapping; appended render nodes do not change the rig.
        source_names = [n.get('name') for n in source_model.get('nodes', [])]
        export_names = [n.get('name') for n in model.get('nodes', [])]
        joints = lambda m: [s.get('joints') for s in m.get('skins', [])]
        if (export_names[:len(source_names)] != source_names
                or joints(model) != joints(source_model)):
            raise BodyPackageError('Export skeleton differs from its mapping source')
        adapter = source.get('adapter')
    if not adapter:
        raise BodyPackageError('Save the model mapping before publishing')
    if mapping_source:
        adapter = save_candidate_mapping(candidates, candidate_id, 'starter_persona',
            {key: adapter.get(key, {}) for key in ['roles','expressions','optical_origin']})
    name = str(name).strip()
    if not name or len(name) > 64:
        raise BodyPackageError('Use an avatar name of 1–64 characters')
    package_id = uuid.uuid4().hex
    result = dict(schema='jnsq-avatar-package/1', package_id=package_id,
                  name=name, candidate_id=candidate_id, adapter=adapter,
                  sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                  design=model.get('extras', {}).get('jnsq_design'),
                  attachments=[], created_at=_now())
    _atomic_json(str(Path(root) / 'packages' / (package_id + '.json')), result)
    return result

def assignments(root):
    path = Path(root) / 'assignments.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}

def render_events(root, events, repo=None):
    """A resident arriving in another room keeps their selected package."""
    registry = assignments(root)
    from core.avatar_identities import member_keys
    aliases=member_keys(repo) if repo else {}
    return [{**event, 'data': {**event.get('data', {}),
                              'avatar_package': registry.get(aliases.get(str(event.get('member', '')).casefold(),str(event.get('member', '')).casefold()), {}).get('package_id')}}
            if event.get('kind') == 'arrive' else event for event in events]

def assign(root, member, package_id, expected_revision=None, restore=False):
    """CAS prevents two editor tabs silently replacing one another's work."""
    member = str(member).strip().casefold()
    if not member or len(member) > 128 or any(ord(c) < 32 for c in member):
        raise BodyPackageError('Invalid member')
    with _LOCK:
        state = assignments(root)
        previous = state.get(member, {})
        if previous.get('revision') != expected_revision:
            raise BodyPackageError('Appearance changed elsewhere; refresh before applying')
        history = list(previous.get('history', []))
        if restore:
            if not history:
                raise BodyPackageError('No previous appearance to restore')
            package_id = history.pop()['package_id']
        else:
            if package_id:
                load_package(root, package_id)
            history.append(dict(package_id=previous.get('package_id'), changed_at=_now()))
        record = dict(member=member, package_id=package_id, revision=uuid.uuid4().hex,
                      history=history, changed_at=_now())
        state[member] = record
        _atomic_json(str(Path(root) / 'assignments.json'), state)
        return record

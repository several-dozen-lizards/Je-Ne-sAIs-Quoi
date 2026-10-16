"""Validate persisted wall/opening and roof edits without silently dropping them."""
import copy
import math
import re


def validate_components(b, texture_ids):
    extras = {}
    if 'roofSections' in b:
        sections = b['roofSections']
        if not isinstance(sections, list) or len(sections) != 4 or any(type(v) is not bool for v in sections):
            raise ValueError('Invalid roof sections')
        extras['roofSections'] = list(sections)
    if 'wallEdits' not in b:
        return extras
    edits = b['wallEdits']; segments = 32 if b['shape'] == 'round' else 4
    if not isinstance(edits, list) or len(edits) > b['floors'] * segments:
        raise ValueError('Too many wall edits')
    seen = set()
    def number(v):
        return type(v) in (int, float) and math.isfinite(v)
    for wall in edits:
        if (not isinstance(wall, dict) or type(wall.get('floor')) is not int
                or not 0 <= wall['floor'] < b['floors'] or type(wall.get('segment')) is not int
                or not 0 <= wall['segment'] < segments or type(wall.get('removed')) is not bool
                or not isinstance(wall.get('openings'), list) or len(wall['openings']) > 12):
            raise ValueError('Invalid exterior wall')
        key = (wall['floor'], wall['segment'])
        if key in seen: raise ValueError('Duplicate exterior wall')
        seen.add(key); i = wall['segment']
        if segments == 32:
            a, c = i / 32 * math.tau, (i + 1) / 32 * math.tau
            length = math.hypot((math.cos(c)-math.cos(a))*b['width']/2, (math.sin(c)-math.sin(a))*b['depth']/2)
        else:
            length = b['width'] if i % 2 == 0 else b['depth']
        ids = set()
        for o in wall['openings']:
            if (not isinstance(o, dict) or not isinstance(o.get('id'), str) or not 1 <= len(o['id']) <= 80 or o['id'] in ids
                    or o.get('kind') not in ('door','window') or o.get('shape') not in ('rectangle','arched','circle','oval','rounded','diamond','triangle','rhomboid')
                    or type(o.get('frames')) is not bool or not all(number(o.get(k)) for k in ('offset','width','bottom','top','opacity','angle'))
                    or o['width'] < .2 or o['bottom'] < 0 or o['top'] > 3.05 or o['top']-o['bottom'] < .2
                    or o.get('glass') not in ('none','clear','stained','image') or not isinstance(o.get('color'), str) or not re.fullmatch(r'#[a-fA-F0-9]{6}',o['color'])
                    or not .05 <= o['opacity'] <= 1 or o.get('door') not in ('none','solid') or not 0 <= o['angle'] <= 120
                    or 'doorStyle' in o and o['doorStyle'] not in ('flat','panelled','medieval','glazed')
                    or 'doorColor' in o and not re.fullmatch(r'#[a-fA-F0-9]{6}',str(o['doorColor']))
                    or 'doorImage' in o and o['doorImage'] not in texture_ids
                    or o['kind'] == 'door' and o['bottom'] != 0 or o['kind'] == 'window' and (o['door'] != 'none' or any(k in o for k in ('doorStyle','doorColor','doorImage')))
                    or 'image' in o and o['image'] not in texture_ids or o['glass'] == 'image' and o.get('image') not in texture_ids):
                raise ValueError('Invalid opening or glazing')
            ids.add(o['id'])
        edge = -length/2-.001
        for o in sorted(wall['openings'], key=lambda o:o['offset']):
            if o['offset']-o['width']/2 < edge or o['offset']+o['width']/2 > length/2+.001:
                raise ValueError('Openings overlap or extend outside the wall')
            edge = o['offset']+o['width']/2+.08
    extras['wallEdits'] = copy.deepcopy(edits)
    return extras

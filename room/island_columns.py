"""Column placement and open pavilion persistence, using the renderer's catalogue."""
import math
import json
from pathlib import Path

STYLES=json.loads((Path(__file__).resolve().parents[1]/'assets/jnaiq/island-workshop/column-styles.json').read_text(encoding='utf-8'))


def number(v,low,high):
    return type(v) in (int,float) and math.isfinite(v) and low <= v <= high


def validate_pavilion(b):
    result={}
    if 'enclosure' in b:
        if b['enclosure'] not in ('walls','columns'): raise ValueError('Invalid enclosure')
        result['enclosure']=b['enclosure']
    if 'columnStyle' in b:
        if not isinstance(b['columnStyle'],str) or b['columnStyle'] not in STYLES: raise ValueError('Invalid column style')
        result['columnStyle']=b['columnStyle']
    if 'columnSpacing' in b:
        if not number(b['columnSpacing'],2,8): raise ValueError('Invalid pavilion spacing')
        result['columnSpacing']=b['columnSpacing']
    return result


def validate_columns(items,size):
    if not isinstance(items,list) or len(items)>160: raise ValueError('Too many column placements')
    result=[];ids=set();count=0
    for c in items:
        if (not isinstance(c,dict) or not isinstance(c.get('id'),str) or not 1<=len(c['id'])<=80 or c['id'] in ids
            or not isinstance(c.get('style'),str) or c['style'] not in STYLES
            or c.get('material') not in ('stone','marble','timber','plaster','concrete','copper','brick')
            or not number(c.get('x'),-size/2,size/2) or not number(c.get('z'),-size/2,size/2)
            or not number(c.get('length'),0,80) or not number(c.get('height'),1,16)
            or not number(c.get('radius'),.1,1.5) or not number(c.get('spacing'),1,12)
            or not number(c.get('rotation'),-math.tau,math.tau) or c['spacing']<c['radius']*4): raise ValueError('Invalid column placement')
        n=math.ceil(c['length']/c['spacing']) if c['length'] else 0
        if n and c['length']/n<c['radius']*4: raise ValueError('Column capitals overlap; lengthen the row or reduce the radius')
        count+=n+1;ids.add(c['id'])
        for t in (-.5,.5):
            x=c['x']+math.cos(c['rotation'])*c['length']*t;z=c['z']-math.sin(c['rotation'])*c['length']*t
            if abs(x)+c['radius']*1.8>size/2 or abs(z)+c['radius']*1.8>size/2: raise ValueError('Column outside island')
        result.append({k:c[k] for k in ('id','style','material','x','z','length','rotation','height','radius','spacing')})
    if count>1000: raise ValueError('Too many columns')
    return result

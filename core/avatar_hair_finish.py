"""Reversible hair texture finishes, shared by preview and export."""
import base64,io,json,struct
from functools import lru_cache
from pathlib import Path
import numpy as np
from PIL import Image

@lru_cache(maxsize=2)
def source_textures(path,mtime,style,category='hair'):
    raw=Path(path).read_bytes();size=struct.unpack_from('<I',raw,12)[0];m=json.loads(raw[20:20+size]);b=raw[28+size:];result={}
    for node in m.get('nodes',[]):
        e=node.get('extras',{})
        if e.get('jnsq_fit_category')!=category or (category=='hair' and e.get('jnsq_fit_asset_name')!=style):continue
        for p in m['meshes'][node['mesh']]['primitives']:
            mat=m['materials'][p['material']];tex=mat.get('pbrMetallicRoughness',{}).get('baseColorTexture')
            if not tex:continue
            im=m['images'][m['textures'][tex['index']]['source']]
            if 'bufferView' in im:
                v=m['bufferViews'][im['bufferView']];data=b[v.get('byteOffset',0):v.get('byteOffset',0)+v['byteLength']]
            elif im.get('uri','').startswith('data:image/'):data=base64.b64decode(im['uri'].split(',',1)[1])
            else:continue
            result[mat['name']]=data
    return result

def finish_pixels(image,color,lightness,highlight,amount,pattern):
    pixels=np.array(image.convert('RGBA'));rgb=pixels[:,:,:3]/255
    tint=np.array([int(color[i:i+2],16)/255 for i in (1,3,5)])
    accent=np.array([int(highlight[i:i+2],16)/255 for i in (1,3,5)])
    # Lift the dark source's detail before tinting, rather than whitening the tint.
    luminance=rgb.max(axis=2)
    detail=.55+.45*np.power(luminance,.45)
    brightness=.45+.55*lightness
    base=detail[:,:,None]*brightness*tint
    h,w=pixels.shape[:2];y,x=np.indices((h,w));u=x/w;v=y/h
    if pattern=='tips':mask=np.clip((v-.45)/.5,0,1);mask=mask*mask*(3-2*mask)
    else:
        frequency=18 if pattern=='fine' else 5
        wave=.5+.5*np.cos(2*np.pi*(u*frequency+.08*np.sin(v*5)))
        mask=np.power(wave,6 if pattern=='fine' else 3)
    detail=.25+.75*np.power(rgb.max(axis=2),.45)
    mix=amount*mask[:,:,None]
    pixels[:,:,:3]=np.rint(np.clip(base*(1-mix)+detail[:,:,None]*accent*mix,0,1)*255).astype('uint8')
    return Image.fromarray(pixels)

@lru_cache(maxsize=12)
def baked(path,mtime,style,color,lightness,highlight,amount,pattern):
    result={}
    for name,raw in source_textures(path,mtime,style).items():
        image=Image.open(io.BytesIO(raw))
        out=finish_pixels(image,color,lightness,highlight,amount,pattern)
        data=io.BytesIO();out.save(data,format='PNG')
        result[name]='data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()
    return result

def resolve_hair(path,appearance):
    path=Path(path)
    return baked(str(path),path.stat().st_mtime_ns,appearance['hairstyle'],appearance['hair'],appearance['hair_lightness'],appearance['hair_highlight_color'],appearance['hair_highlight_amount'],appearance['hair_highlight_pattern'])

@lru_cache(maxsize=12)
def clothing_baked(path,mtime,color,top,bottom):
    result={}
    for name,raw in source_textures(path,mtime,'','clothes').items():
        chosen=top if name.lower()=='jnsq.top' and top!='#ffffff' else bottom if name.lower()=='jnsq.bottom' and bottom!='#ffffff' else color
        image=Image.open(io.BytesIO(raw)).convert('RGBA');pixels=np.array(image)
        if chosen!='#ffffff':
            rgb=pixels[:,:,:3]/255;lum=rgb.max(axis=2)
            tint=np.array([int(chosen[i:i+2],16)/255 for i in (1,3,5)])
            pixels[:,:,:3]=np.rint((.6+.4*lum)[:,:,None]*tint*255).astype('uint8')
        out=io.BytesIO();Image.fromarray(pixels).save(out,format='PNG')
        result[name]='data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()
    return result

def resolve_clothing(path,appearance):
    path=Path(path)
    return clothing_baked(str(path),path.stat().st_mtime_ns,*[appearance[k] for k in ['outfit','outfit_top','outfit_bottom']])

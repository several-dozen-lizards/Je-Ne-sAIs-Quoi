"""Change a fitted outfit while retaining the current character assembly.

Compiled outfits share MakeHuman surface coordinates. Exact body matches keep
the authored geometry and every shape. Garment corrections are transferred from
the current fitted outfit, so later character shapes follow the new clothes.
Each result is a new candidate; inputs and saved designs are never rewritten.
"""
import copy,hashlib,json,struct,threading
from pathlib import Path
import numpy as np
from core.body_packages import BodyPackageError
from core.body_candidates import CandidateStager,candidate_model_path,load_candidate,save_candidate_mapping
from tools.mix_avatar_clothes import load
from tools.optimize_avatar_textures import accessor_array
from tools.compact_avatar_preview import compact
from tools.upgrade_avatar_shape_range import uv_array

_lock=threading.Lock()
VERSION='wardrobe-character-2'

def category(n):return n.get('extras',{}).get('jnsq_fit_category','body')
def mesh_node(m,cat):return next(n for n in m['nodes'] if 'mesh' in n and category(n)==cat)
def xyz(m,b,p,name=None,semantic='POSITION'):
 return accessor_array(m,b,p['attributes'][semantic] if name is None else p['targets'][name][semantic])

def neighbours(source,points,k=6):
 # Bounded batches avoid an N x M allocation for a whole garment.
 indices=[];weights=[]
 for chunk in np.array_split(points,max(1,(len(points)+127)//128)):
  d=np.sum((chunk[:,None,:]-source[None,:,:])**2,axis=2)
  ix=np.argpartition(d,min(k,d.shape[1])-1,axis=1)[:,:k]
  ds=np.take_along_axis(d,ix,axis=1);w=1/np.maximum(ds,1e-10)**2;w/=w.sum(1)[:,None]
  indices.append(ix);weights.append(w)
 return np.concatenate(indices),np.concatenate(weights)

def interpolate(values,binding):
 ix,w=binding;return np.sum(values[ix]*w[:,:,None],axis=1)

def compose(source_path,outfit_path,reference_path,dest):
 m,b=load(source_path);donor,db=load(outfit_path);reference,rb=load(reference_path)
 source_body=mesh_node(m,'body');source_clothes=mesh_node(m,'clothes')
 donor_body=mesh_node(donor,'body');donor_clothes=mesh_node(donor,'clothes')
 sm=m['meshes'][source_body['mesh']];sp=sm['primitives'][0]
 dm=donor['meshes'][donor_body['mesh']];dp=dm['primitives'][0]
 sv=xyz(m,b,sp);dv=xyz(donor,db,dp);names=sm['extras']['targetNames']
 if 'JNAIQ_BodyFrame_Feminine' not in names:raise BodyPackageError('This outfit needs a compatible editable human body.')
 if len(sm['primitives'])!=1 or len(dm['primitives'])!=1:raise BodyPackageError('Body surface layout is not supported by this outfit.')
 # Bone indices in garment attributes must have the identical meaning.
 def joints(model,node):return [model['nodes'][i]['name'] for i in model['skins'][node['skin']]['joints']]
 source_joints=joints(m,source_body);donor_joints=joints(donor,donor_body)
 if not set(donor_joints)<=set(source_joints):raise BodyPackageError('This outfit uses a different skeleton.')
 joint_map=np.array([source_joints.index(name) for name in donor_joints],dtype='<u2')
 table={tuple(np.round(p,6)):i for i,p in enumerate(uv_array(m,b,sp))}
 match=np.array([table.get(tuple(np.round(p,6)),-1) for p in uv_array(donor,db,dp)]);valid=match>=0
 if np.mean(valid[dv[:,1]>1.42])<.999 or np.max(np.abs(sv[match[valid]]-dv[valid]))>.15:raise BodyPackageError('This outfit does not share the current character’s head surface.')
 # Read correction fields before replacing anything. Original garment fitting
 # remains the baseline; only changes authored since that fitting are added.
 cm=m['meshes'][source_clothes['mesh']];rm=reference['meshes'][mesh_node(reference,'clothes')['mesh']]
 cv=np.concatenate([xyz(m,b,p) for p in cm['primitives']])
 rv=np.concatenate([xyz(reference,rb,p) for p in rm['primitives']])
 ref_bind=neighbours(rv,cv)
 cn=cm['extras']['targetNames'];rn=rm['extras']['targetNames']
 fields={}
 for name in names:
  current=np.concatenate([xyz(m,b,p,cn.index(name)) if name in cn else np.zeros_like(xyz(m,b,p)) for p in cm['primitives']])
  old=np.concatenate([xyz(reference,rb,p,rn.index(name)) if name in rn else np.zeros_like(xyz(reference,rb,p)) for p in rm['primitives']])
  field=current-interpolate(old,ref_bind)
  if np.max(np.abs(field))>2e-6:fields[name]=field
 copied={}
 def move(kind,i):
  if (kind,i) in copied:return copied[kind,i]
  value=copy.deepcopy(donor[kind][i])
  if kind=='bufferViews':
   off=value.get('byteOffset',0);data=db[off:off+value['byteLength']];b.extend(b'\0'*(-len(b)%4));value.update(buffer=0,byteOffset=len(b));b.extend(data)
  elif kind=='accessors':
   if 'bufferView' in value:value['bufferView']=move('bufferViews',value['bufferView'])
   for part in value.get('sparse',{}).values():
    if isinstance(part,dict) and 'bufferView' in part:part['bufferView']=move('bufferViews',part['bufferView'])
  elif kind=='images':
   if 'bufferView' in value:value['bufferView']=move('bufferViews',value['bufferView'])
  elif kind=='textures':
   value['source']=move('images',value['source'])
   if 'sampler' in value:value['sampler']=move('samplers',value['sampler'])
  elif kind=='materials':
   def visit(obj):
    for k,v in obj.items():
     if isinstance(v,dict):
      if k.endswith('Texture') and 'index' in v:v['index']=move('textures',v['index'])
      else:visit(v)
   visit(value)
  idx=len(m.setdefault(kind,[]));m[kind].append(value);copied[kind,i]=idx;return idx
 def store(values):
  v=np.asarray(values,dtype='<f4');a={'componentType':5126,'count':len(v),'type':'VEC3','min':v.min(0).tolist(),'max':v.max(0).tolist()}
  if np.any(v):
   b.extend(b'\0'*(-len(b)%4));a['bufferView']=len(m['bufferViews']);m['bufferViews'].append({'buffer':0,'byteOffset':len(b),'byteLength':v.nbytes});b.extend(v.tobytes())
  idx=len(m['accessors']);m['accessors'].append(a);return idx
 def transfer(node,body=False):
  old_mesh=donor['meshes'][node['mesh']];new=copy.deepcopy(old_mesh);dn=old_mesh['extras']['targetNames']
  new['extras']['targetNames']=list(names);new['weights']=list(sm.get('weights',[0]*len(names)))
  for p,old in zip(new['primitives'],old_mesh['primitives']):
   pos=xyz(donor,db,old);bind=neighbours(cv,pos) if fields else None
   p['attributes']={k:move('accessors',v) for k,v in old['attributes'].items()};p['indices']=move('accessors',old['indices'])
   for sem,ai in old['attributes'].items():
    if not sem.startswith('JOINTS_'):continue
    a=donor['accessors'][ai];v=donor['bufferViews'][a['bufferView']];dtype={5121:'u1',5123:'<u2'}[a['componentType']]
    ix=np.ndarray((a['count'],4),dtype=dtype,buffer=db,offset=v.get('byteOffset',0)+a.get('byteOffset',0),strides=(v.get('byteStride',4*np.dtype(dtype).itemsize),np.dtype(dtype).itemsize))
    data=joint_map[ix].tobytes();b.extend(b'\0'*(-len(b)%4));bv=len(m['bufferViews']);m['bufferViews'].append({'buffer':0,'byteOffset':len(b),'byteLength':len(data)});b.extend(data)
    p['attributes'][sem]=len(m['accessors']);m['accessors'].append({'bufferView':bv,'componentType':5123,'count':len(ix),'type':'VEC4'})
   p['material']=sp['material'] if body else move('materials',old['material'])
   if body:
    for sem in ['POSITION','NORMAL']:
     v=xyz(donor,db,old,semantic=sem);v[valid]=xyz(m,b,sp,semantic=sem)[match[valid]];p['attributes'][sem]=store(v)
   p['targets']=[]
   for name in names:
    target={}
    for sem in ['POSITION','NORMAL']:
     v=xyz(donor,db,old,dn.index(name),sem) if name in dn and sem in old['targets'][dn.index(name)] else np.zeros_like(pos)
     if sem=='POSITION' and name in fields:v+=interpolate(fields[name],bind)
     if body and sem in sp['targets'][names.index(name)]:v[valid]=xyz(m,b,sp,names.index(name),sem)[match[valid]]
     target[sem]=store(v)
    p['targets'].append(target)
  mi=len(m['meshes']);m['meshes'].append(new);return mi
 source_body['mesh']=transfer(donor_body,True)
 source_clothes['mesh']=transfer(donor_clothes)
 source_clothes['skin']=source_body['skin']
 source_clothes['name']=donor_clothes['name'];source_clothes['extras']=copy.deepcopy(donor_clothes.get('extras',{}))
 # Node defaults override mesh defaults in glTF.
 for node in [source_body,source_clothes]:
  if 'weights' in node:node['weights']=list(sm.get('weights',[0]*len(names)))
 # Retain the original fitting reference across repeated outfit changes.
 m.setdefault('extras',{})['jnsq_wardrobe_version']=VERSION
 used=sorted({node['mesh'] for node in m['nodes'] if 'mesh' in node});remap={old:i for i,old in enumerate(used)}
 m['meshes']=[m['meshes'][i] for i in used]
 for node in m['nodes']:
  if 'mesh' in node:node['mesh']=remap[node['mesh']]
 b.extend(b'\0'*(-len(b)%4));m['buffers']=[{'byteLength':len(b)}]
 raw=json.dumps(m,separators=(',',':')).encode();raw+=b' '*(-len(raw)%4)
 Path(dest).write_bytes(struct.pack('<IIIII',0x46546c67,2,28+len(raw)+len(b),len(raw),0x4e4f534a)+raw+struct.pack('<II',len(b),0x004e4942)+b)
 return {'matched_body_vertices':int(valid.sum()),'body_vertices':len(dv),'transferred_garment_shapes':list(fields)}

def change(repo,root,candidates,source_id,outfit_id):
 entries=json.loads((Path(repo)/'room/avatar_starters.json').read_text())['starters']
 outfits=[x for x in entries if x.get('asset') or x.get('pieces')]
 outfit=next((x for x in outfits if x['candidate_id']==outfit_id),None)
 if outfit is None:raise BodyPackageError('Choose an outfit from the wardrobe.')
 source=Path(candidate_model_path(candidates,source_id,'starter_persona'))
 donor=Path(candidate_model_path(candidates,outfit_id,'starter_persona'))
 # A cached composition is based on source bytes, not a mutable design name.
 key=hashlib.sha256(VERSION.encode()+source.read_bytes()+donor.read_bytes()).hexdigest()
 folder=Path(root)/'wardrobe'/key
 with _lock:
  receipt=folder/'result.json'
  if receipt.exists():
   result=json.loads(receipt.read_text());candidate_model_path(candidates,result['candidate_id'],'starter_persona');return result
  current,_=load(source)
  # A coat may hide neck triangles that a dress later reveals. Reuse the full
  # character source, so repeated outfit changes never accumulate lost anatomy
  # or interpolation error from the previous garment.
  character_id=current.get('extras',{}).get('jnsq_wardrobe_character',source_id)
  character=Path(candidate_model_path(candidates,character_id,'starter_persona'))
  model,_=load(character);asset=mesh_node(model,'clothes').get('extras',{}).get('jnsq_fit_asset_name')
  baseline=next((x for x in outfits if x.get('asset')==asset),None)
  # Separates keep the source candidate ID in their provenance.
  prior=model.get('extras',{}).get('jnsq_wardrobe_outfit')
  if prior:baseline=next((x for x in outfits if x['candidate_id']==prior),baseline)
  if baseline is None:raise BodyPackageError('The current custom outfit needs its fitting reference before it can be exchanged.')
  reference=candidate_model_path(candidates,baseline['candidate_id'],'starter_persona')
  folder.mkdir(parents=True,exist_ok=True);dest=folder/'assembly.glb'
  report=compose(character,donor,reference,dest)
  # Add provenance before staging, keeping the staged content immutable.
  raw=dest.read_bytes();n=struct.unpack_from('<I',raw,12)[0];m=json.loads(raw[20:20+n]);m.setdefault('extras',{})['jnsq_wardrobe_outfit']=outfit_id
  m['extras']['jnsq_wardrobe_character']=character_id
  if outfit.get('pieces'):mesh_node(m,'clothes')['extras']['jnsq_fit_asset_name']='separates:'+outfit['top']+':'+outfit['bottom']
  j=json.dumps(m,separators=(',',':')).encode();j+=b' '*(-len(j)%4)
  dest.write_bytes(struct.pack('<IIIII',0x46546c67,2,len(raw)-n+len(j),len(j),0x4e4f534a)+j+raw[20+n:])
  stage=CandidateStager(candidates,outfit['name']+' - current character.glb','starter_persona')
  with dest.open('rb') as f:
   while chunk:=f.read(1024*1024):stage.write(chunk)
  stage.finalize()
  adapter=load_candidate(candidates,source_id,'starter_persona')['adapter']
  if adapter:save_candidate_mapping(candidates,stage.candidate_id,'starter_persona',{k:adapter[k] for k in ['roles','expressions','optical_origin']})
  target=Path(candidates)/stage.candidate_id
  compact(target/'body.glb',target/'preview-compact-v2.glb')
  result={'candidate_id':stage.candidate_id,'outfit_id':outfit_id,'name':outfit['name'],'report':report}
  receipt.write_text(json.dumps(result,indent=2));return result

def change_to_model(repo,root,candidates,source_id,donor_path,name,outfit_token):
 """Fit a trusted, already-compiled composite outfit to one character."""
 entries=json.loads((Path(repo)/'room/avatar_starters.json').read_text())['starters']
 outfits=[x for x in entries if x.get('asset') or x.get('pieces')]
 source=Path(candidate_model_path(candidates,source_id,'starter_persona'))
 donor=Path(donor_path)
 key=hashlib.sha256((VERSION+'-pieces').encode()+source.read_bytes()+donor.read_bytes()).hexdigest()
 folder=Path(root)/'wardrobe-pieces'/key
 with _lock:
  receipt=folder/'result.json'
  if receipt.exists():
   result=json.loads(receipt.read_text());candidate_model_path(candidates,result['candidate_id'],'starter_persona');return result
  current,_=load(source)
  character_id=current.get('extras',{}).get('jnsq_wardrobe_character',source_id)
  character=Path(candidate_model_path(candidates,character_id,'starter_persona'))
  model,_=load(character);asset=mesh_node(model,'clothes').get('extras',{}).get('jnsq_fit_asset_name')
  baseline=next((x for x in outfits if x.get('asset')==asset),None)
  prior=model.get('extras',{}).get('jnsq_wardrobe_outfit')
  if prior:baseline=next((x for x in outfits if x['candidate_id']==prior),baseline)
  if baseline is None:raise BodyPackageError('The current custom outfit needs its fitting reference before it can be exchanged.')
  reference=candidate_model_path(candidates,baseline['candidate_id'],'starter_persona')
  folder.mkdir(parents=True,exist_ok=True);dest=folder/'assembly.glb'
  report=compose(character,donor,reference,dest)
  raw=dest.read_bytes();n=struct.unpack_from('<I',raw,12)[0];m=json.loads(raw[20:20+n])
  m.setdefault('extras',{})['jnsq_wardrobe_outfit']=outfit_token
  m['extras']['jnsq_wardrobe_character']=character_id
  j=json.dumps(m,separators=(',',':')).encode();j+=b' '*(-len(j)%4)
  dest.write_bytes(struct.pack('<IIIII',0x46546c67,2,len(raw)-n+len(j),len(j),0x4e4f534a)+j+raw[20+n:])
  stage=CandidateStager(candidates,name+' - current character.glb','starter_persona')
  with dest.open('rb') as handle:
   while chunk:=handle.read(1024*1024):stage.write(chunk)
  stage.finalize()
  adapter=load_candidate(candidates,source_id,'starter_persona')['adapter']
  if adapter:save_candidate_mapping(candidates,stage.candidate_id,'starter_persona',{k:adapter[k] for k in ['roles','expressions','optical_origin']})
  target=Path(candidates)/stage.candidate_id
  compact(target/'body.glb',target/'preview-compact-v2.glb')
  result={'candidate_id':stage.candidate_id,'outfit_id':outfit_token,'name':name,'report':report}
  receipt.write_text(json.dumps(result,indent=2));return result

"""Asynchronously fit allowlisted local wardrobe pieces into one outfit."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import subprocess
import threading
import uuid
from pathlib import Path

from core.body_candidates import candidate_model_path
from core.body_packages import BodyPackageError


EXECUTOR=ThreadPoolExecutor(max_workers=1,thread_name_prefix='avatar-wardrobe-pieces')
LOCK=threading.Lock()
CHANGED=threading.Condition(LOCK)
SLOTS=('top','bottom','outerwear','shoes','hat')


def _build_key(repo,source,body_source,ordered,selection):
 digest=hashlib.sha256(json.dumps(ordered,sort_keys=True).encode())
 digest.update(source.read_bytes())
 body=Path(body_source)
 digest.update(f'{body.stat().st_size}:{body.stat().st_mtime_ns}'.encode())
 for relative in ('core/avatar_piece_jobs.py','core/avatar_wardrobe.py','tools/convert_makehuman_jnaiq.py','tools/merge_avatar_clothing.py'):
  digest.update((Path(repo)/relative).read_bytes())
 for slot in SLOTS:
  if slot in selection:digest.update((Path(repo)/selection[slot]['source']).read_bytes())
 return digest.hexdigest()


def catalog(repo,public=False):
 document=json.loads((Path(repo)/'room/avatar_wardrobe_pieces.json').read_text(encoding='utf-8'))
 if public:
  return {'schema':document['schema'],'pieces':[{k:v for k,v in piece.items() if k not in {'source','notices','license_source'}} for piece in document['pieces']]}
 return document


def recover_interrupted(root):
 for path in (Path(root)/'piece_jobs').glob('*/job.json'):
  record=json.loads(path.read_text())
  if record.get('status') in {'queued','fitting'}:
   record.update(status='failed',error='Fitting was interrupted. Choose Wear these pieces to retry.')
   path.write_text(json.dumps(record),encoding='utf-8')


def start(repo,root,candidates,source_id,values):
 available={piece['id']:piece for piece in catalog(repo)['pieces']}
 requested=values.get('pieces') if isinstance(values,dict) else None
 if not isinstance(requested,dict):raise BodyPackageError('Choose wardrobe pieces first')
 selection={}
 for slot,value in requested.items():
  if slot not in SLOTS or not isinstance(value,str):raise BodyPackageError('Invalid wardrobe piece selection')
  if value in {'','none'}:continue
  piece=available.get(value)
  if piece is None or piece['slot']!=slot:raise BodyPackageError('Wardrobe piece is not available in that section')
  selection[slot]=piece
 if not {'top','bottom'}<=set(selection):raise BodyPackageError('Choose both a top and a bottom')
 source=Path(candidate_model_path(candidates,source_id,'starter_persona'))
 from tools.build_avatar_wardrobe import BLENDER,SOURCE
 blender=os.environ.get('JNAIQ_BLENDER',BLENDER);body_source=os.environ.get('JNAIQ_AVATAR_SOURCE_BLEND',SOURCE)
 if not Path(blender).is_file() or not Path(body_source).is_file():raise BodyPackageError('Local fitting needs Blender, MPFB and the editable JNAIQ human source')
 ordered={slot:selection[slot]['id'] for slot in SLOTS if slot in selection}
 build_key=_build_key(repo,source,body_source,ordered,selection)
 for path in (Path(root)/'piece_jobs').glob('*/job.json'):
  previous=json.loads(path.read_text())
  if previous.get('build_key')==build_key and previous.get('status') in {'queued','fitting','ready'}:
   if previous['status']!='ready' or (Path(candidates)/previous['candidate_id']).is_dir():return previous
 directory=Path(root)/'piece_jobs'/uuid.uuid4().hex;directory.mkdir(parents=True)
 name=' + '.join(selection[slot]['name'] for slot in SLOTS if slot in selection)
 record={'job_id':directory.name,'status':'queued','build_key':build_key,'pieces':ordered,'name':name}
 def save():
  with CHANGED:
   temporary=directory/'job.partial';temporary.write_text(json.dumps(record),encoding='utf-8');os.replace(temporary,directory/'job.json');CHANGED.notify_all()
 save()
 def work():
  try:
   record['status']='fitting';save()
   from tools.build_avatar_wardrobe import anatomy_assets
   output=directory/'donor.glb';manifest=directory/'conversion.json'
   command=[blender,'--background','--python-exit-code','1','--python',str(Path(repo)/'tools/convert_makehuman_jnaiq.py'),'--','--source',body_source,'--output',str(output),'--manifest',str(manifest)]
   for spec in anatomy_assets():command+=['--asset',spec]
   slots={}
   for slot,piece in selection.items():
    definition=(Path(repo)/piece['source']).resolve()
    if not definition.is_relative_to(Path(repo).resolve()) or not definition.is_file():raise BodyPackageError('Wardrobe source is unavailable')
    command+=['--asset','clothes:'+str(definition)];slots[piece['id']]=slot
   with (directory/'build.log').open('w',encoding='utf-8') as log:
    subprocess.run(command,cwd=repo,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=2400,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   from tools.optimize_avatar_textures import optimize
   from tools.add_avatar_contour_morphs import refine
   from tools.merge_avatar_clothing import merge
   optimize(output);refine(output,output);merge(output,slots)
   from core.avatar_wardrobe import change_to_model
   token='pieces:'+','.join(f'{slot}={ordered[slot]}' for slot in ordered)
   result=change_to_model(repo,root,candidates,source_id,output,name,token)
   record.update(status='ready',candidate_id=result['candidate_id'],result=result);save()
  except Exception as error:
   record.update(status='failed',error=str(error) or type(error).__name__);save()
 EXECUTOR.submit(work)
 return record.copy()


def status(root,job,after=None):
 if not re.fullmatch('[a-f0-9]{32}',job):raise BodyPackageError('Invalid wardrobe job')
 path=Path(root)/'piece_jobs'/job/'job.json'
 if not path.is_file():raise BodyPackageError('Wardrobe job unavailable')
 with CHANGED:
  if after:CHANGED.wait_for(lambda:json.loads(path.read_text())['status']!=after,timeout=25)
  return json.loads(path.read_text())

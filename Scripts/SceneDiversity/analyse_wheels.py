import json
from pathlib import Path
import numpy as np
root=Path(__file__).resolve().parents[2];out=root/'Saved/SceneDiversity'
result={}
for name in ('Hatchback','SUV','Pickup','SportsCar','Truck_Box'):
 vertices=[];faces=[]
 for line in (out/(name+'.obj')).read_text().splitlines():
  if line.startswith('v '):vertices.append([float(v) for v in line.split()[1:]])
  elif line.startswith('f '):faces.append([int(v.split('/')[0])-1 for v in line.split()[1:]])
 v=np.array(vertices)[:,[0,2,1]];unique,inverse=np.unique(np.round(v,3),axis=0,return_inverse=True);parent=list(range(len(unique)))
 def find(i):
  while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
  return i
 for f in faces:
  ids=[find(int(inverse[i])) for i in f]
  for i in ids[1:]:parent[find(i)]=find(ids[0])
 roots=np.array([find(int(i)) for i in inverse]);candidates=[]
 for r in np.unique(roots):
  p=v[roots==r];lo=p.min(0);hi=p.max(0);c=(lo+hi)/2;size=hi-lo
  if len(p)<24 or abs(c[1])<40 or lo[2]<-8 or hi[2]>95 or not 30<size[0]<100 or not 25<size[2]<100 or size[1]>65:continue
  candidates.append({'vertices':len(p),'min':lo.tolist(),'max':hi.tolist(),'center':c.tolist(),'extent':(size/2).tolist()})
 result[name]=candidates
(out/'wheel_candidates.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

"""Find nearest outward-facing render triangles for reproducible hot-part probes."""
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]


def prepare():
    geometry=json.loads((ROOT/'Config/SceneDiversity/vehicle_geometry.json').read_text())
    alignment=json.loads((ROOT/'Config/SceneDiversity/source_alignment.json').read_text())
    result={}
    for model,asset in geometry.items():
        vertices=[];normals=[];faces=[];normal_ids=[]
        for line in (ROOT/'Saved/SceneDiversity'/(model+'.obj')).read_text().splitlines():
            if line.startswith('v '):vertices.append(list(map(float,line.split()[1:4])))
            elif line.startswith('vn '):normals.append(list(map(float,line.split()[1:4])))
            elif line.startswith('f '):
                terms=[term.split('/') for term in line.split()[1:]]
                if len(terms)!=3:continue
                faces.append([int(t[0])-1 for t in terms]);normal_ids.append(int(terms[0][2])-1 if len(terms[0])>2 and terms[0][2] else -1)
        v=np.array(vertices)[:,[0,2,1]];tri=v[np.array(faces)]
        a,b,c=tri[:,0],tri[:,1],tri[:,2];ab=b-a;ac=c-a
        n=np.cross(ab,ac);length=np.linalg.norm(n,axis=1);n/=np.maximum(length,1e-12)[:,None]
        if normals and min(normal_ids)>=0:
            authored=np.array(normals)[:,[0,2,1]][np.array(normal_ids)]
            n[np.einsum('ij,ij->i',n,authored)<0]*=-1
        elif np.einsum('ij,ij->i',a,np.cross(b,c)).sum()<0:
            n*=-1
        targets={'HoodHeat':alignment.get(model,{}).get('hood_cm',asset['hood_cm'])}
        for i,sign in enumerate((-1,1)):
            p=list(asset['headlight_cm']);p[0]=alignment.get(model,{}).get('headlight_x_cm',p[0]);p[1]*=sign
            targets['Headlight_'+str(i)]=p
        result[model]={}
        for name,target in targets.items():
            point=np.array(target,dtype=float)
            desired=np.array([0,0,1] if name=='HoodHeat' and model!='Truck_Box' else [1,0,0])
            projected=point-n*np.einsum('ij,ij->i',point-a,n)[:,None]
            ap=projected-a;d00=np.einsum('ij,ij->i',ab,ab);d01=np.einsum('ij,ij->i',ab,ac);d11=np.einsum('ij,ij->i',ac,ac)
            den=np.maximum(d00*d11-d01*d01,1e-20)
            u=(d11*np.einsum('ij,ij->i',ap,ab)-d01*np.einsum('ij,ij->i',ap,ac))/den
            w=(d00*np.einsum('ij,ij->i',ap,ac)-d01*np.einsum('ij,ij->i',ap,ab))/den
            candidates=[projected]
            distances=[np.where((u>=0)&(w>=0)&(u+w<=1),np.linalg.norm(projected-point,axis=1),np.inf)]
            for start,end in ((a,b),(b,c),(c,a)):
                edge=end-start;t=np.clip(np.einsum('ij,ij->i',point-start,edge)/np.maximum(np.einsum('ij,ij->i',edge,edge),1e-20),0,1)
                q=start+edge*t[:,None];candidates.append(q);distances.append(np.linalg.norm(q-point,axis=1))
            ds=np.array(distances);ds[:,(n@desired<.35)|(length<1e-8)]=np.inf
            ci,ti=np.unravel_index(np.argmin(ds),ds.shape)
            assert ds[ci,ti]<50,(model,name,float(ds[ci,ti]))
            # An emitter can lie between a visible shell and an interior panel.
            # Pick the first rendered face from outside, avoiding the nearer
            # hidden interior and avoiding inflated simple-collision hulls.
            origin=point+desired*150;direction=-desired
            cross=np.cross(np.broadcast_to(direction,ac.shape),ac)
            det=np.einsum('ij,ij->i',ab,cross)
            inv=np.divide(1.,det,out=np.zeros_like(det),where=np.abs(det)>1e-9)
            delta=origin-a;ru=np.einsum('ij,ij->i',delta,cross)*inv
            q=np.cross(delta,ab);rv=(q@direction)*inv
            rt=np.einsum('ij,ij->i',ac,q)*inv
            valid=(np.abs(det)>1e-9)&(ru>=-1e-6)&(rv>=-1e-6)&(ru+rv<=1+1e-6)&(rt>=0)&(rt<=300)
            assert valid.any(),(model,name,'no rendered ray hit')
            ti=int(np.argmin(np.where(valid,rt,np.inf)));probe=origin+direction*rt[ti]
            normal=n[ti] if n[ti]@desired>=0 else -n[ti]
            result[model][name]={'point_cm':probe.tolist(),'normal':normal.tolist(),
                'distance_to_emitter_cm':float(np.linalg.norm(probe-point)),'triangle':ti,'method':'first exterior ray intersection on original exported render mesh'}
    (ROOT/'Config/SceneDiversity/hot_surface_probes.json').write_text(json.dumps(result,indent=2))
    return {m:{n:round(p['distance_to_emitter_cm'],3) for n,p in probes.items()} for m,probes in result.items()}


if __name__=='__main__':print(json.dumps(prepare()))

"""Create explicit, independently editable multi-angle views (no interpolated route)."""
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def prepare():
    scene=next(s for s in json.loads((ROOT/'Config/SceneDiversity/scenes.json').read_text())['scenes']
               if s['id']=='05_combined_environment')
    views=[]
    def add(identity,zone,target,azimuth,radius,height,focus):
        angle=math.radians(azimuth)
        position=[round(target[0]+radius*math.cos(angle),2),round(target[1]+radius*math.sin(angle),2),round(target[2]+height,2)]
        views.append({'id':identity,'zone':zone,'focus':focus,'position_cm':position,'target_cm':list(target),
                      'azimuth_deg':azimuth%360,'elevation_deg':round(math.degrees(math.atan2(height,radius)),3)})
    for zone in scene['zones']:
        name=zone['id']
        vehicles=[v for v in scene['vehicles'] if v['zone']==name]
        per_car=2 if name=='parking' else 3
        for v in vehicles:
            target=list(v['start_cm']);target[2]+=90 if v['model']=='Truck_Box' else 60
            for i,angle in enumerate((35,155,275)[:per_car]):
                add(name+'_'+v['model']+'_'+v['state']+'_'+str(i+1),name,target,
                    (v['yaw']+angle)%360,(1000,1150,1350)[i],(400,600,800)[i],v['label'])
        center=list(zone['center_cm']);center[2]=220
        for i,angle in enumerate((25,145,255)):
            add(name+'_wide_'+str(i+1),name,center,angle,2300,(800,1300,1700)[i],'zone_overview')
        if name in ('cafe','service'):
            target=[center[0],center[1]-750,200]
            add(name+'_props',name,target,90,1100,500,'props')
        elif name=='parking':
            add(name+'_high',name,center,315,2000,2300,'zone_overview')
    assert len(views)==50,len(views)
    for view in views:
        if view['id']=='service_props':target=[-23850,13800,175];angle=90;radius=1000;height=500
        elif view['id']=='service_wide_2':target=[-22100,13900,210];angle=145;radius=1800;height=900;view['id']='service_container'
        elif view['id']=='market_wide_2':target=[-13800,10000,145];angle=145;radius=1100;height=500;view['id']='market_solar_panel'
        else:continue
        view['target_cm']=target
        view['position_cm']=[round(target[0]+radius*math.cos(math.radians(angle)),2),round(target[1]+radius*math.sin(math.radians(angle)),2),target[2]+height]
        view['azimuth_deg']=angle;view['elevation_deg']=math.degrees(math.atan2(height,radius))
    result={'scene':scene['id'],'capture_mode':'independent_viewpoints','units':'Unreal centimetres',
            'description':'Explicit still viewpoints. Camera teleports; no route interpolation or continuous recording.',
            'views':views}
    (ROOT/'Config/SceneDiversity/viewpoints.json').write_text(json.dumps(result,indent=2)+'\n')
    return len(views)


if __name__=='__main__':
    print(prepare())

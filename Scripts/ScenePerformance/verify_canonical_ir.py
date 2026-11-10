"""Compare GPU display against independent CPU radiance/surface lookup on the same inputs."""
import json
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'RouteCaptureDemo'))
from editor_command import ROOT,editor
output=ROOT/'Saved/ProjectMaintenance'
reports=[]
poses=[('car',"position=car.get_actor_transform().transform_location(unreal.Vector(500,-350,280));target=car.get_actor_transform().transform_location(unreal.Vector(120,0,80))"),('area',"target=car.get_actor_location()+unreal.Vector(0,0,450);position=car.get_actor_location()+unreal.Vector(-1500,-1700,650)"),('lamp',"fixture=min((s for s in heat_sources if s.actor_has_tag('ThermalEveningFixture') and 'StreetLamp' in s.get_class().get_name()),key=lambda s:(s.get_actor_location()-car.get_actor_location()).length());target=fixture.get_actor_location();position=target+unreal.Vector(400,-400,-160)")]
try:
    for label,pose in poses:
        editor(pose+"\nrotation=unreal.MathLibrary.find_look_at_rotation(position,target)\nfor camera in cameras:camera.set_actor_location_and_rotation(position,rotation,False,True)\nunreal.SystemLibrary.execute_console_command(world,'airsim.Thermal.LiveHz 30')\nresult=True")
        time.sleep(2)
        gpu=output/(label+'_gpu.png');cpu=output/(label+'_cpu.png')
        editor("unreal.SystemLibrary.execute_console_command(world,'airsim.Thermal.LiveHz 0')\nresult=True")
        assert editor(f'result=hud.save_thermal_gpu_preview({str(gpu)!r})')
        assert editor(f'result=hud.save_thermal_cpu_reference({str(cpu)!r})')
        a=np.asarray(Image.open(gpu).convert('RGB'),dtype=np.float32)
        b=np.asarray(Image.open(cpu).convert('RGB'),dtype=np.float32)
        assert a.shape==b.shape==(720,1280,3)
        delta=np.abs(a-b)[:,:,0]
        report={'view':label,'size':[1280,720],'mean_abs_counts':float(delta.mean()),'p95_abs_counts':float(np.quantile(delta,.95)),'max_abs_counts':float(delta.max()),'pixels_over_10_counts':int((delta>10).sum())}
        reports.append(report)
        print(json.dumps(report),flush=True)
        assert report['mean_abs_counts']<1.0 and report['p95_abs_counts']<=2.0,report
finally:
    editor("unreal.SystemLibrary.execute_console_command(world,'airsim.Thermal.LiveHz 30');result=True")
(output/'canonical_ir_parity.json').write_text(json.dumps(reports,indent=2))

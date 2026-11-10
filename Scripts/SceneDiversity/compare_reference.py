import json,sys,time
from pathlib import Path
import numpy as np
from PIL import Image
import airsim
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'Scripts/RouteCaptureDemo'))
from editor_command import editor
out=root/'Saved/SceneDiversity';client=airsim.VehicleClient(ip='127.0.0.1',port=41471,timeout_value=180)
was_paused=client.simIsPause();initial=editor('result=diversity_snapshot()');was_suspended=bool(initial.get('suspended',False));editor('result=diversity_suspend(True)');client.simPause(True)
try:
 client.client.call('simGetImages',[airsim.ImageRequest('0',12,False,True)],'EveningSample')
 result=editor("""def save_frozen_reference():
 world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
 hud=unreal.GameplayStatics.get_all_actors_of_class(world,unreal.load_class(None,'/Script/AirSim.SimHUD'))[0]
 assert hud.save_thermal_gpu_preview(str(ROOT/'Saved/SceneDiversity/reference_gpu.png'))
 assert hud.save_thermal_cpu_reference(str(ROOT/'Saved/SceneDiversity/reference_cpu.png'))
 return json.loads(hud.get_thermal_gpu_stats())
result=save_frozen_reference()
""",timeout=240)
 a=np.array(Image.open(out/'reference_gpu.png').convert('RGB')).astype(float);b=np.array(Image.open(out/'reference_cpu.png').convert('RGB')).astype(float);e=np.abs(a-b)
 report={'scene':initial.get('id'),'mae_uint8':float(e.mean()),'p95_uint8':float(np.percentile(e,95)),'max_uint8':float(e.max()),'size':[1280,720],'gpu':result,'scope':'Independent CPU surface/radiance arithmetic using the same opaque/masked camera geometry inputs. Not physical calibration.'}
 (out/'cpu_gpu_comparison.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));assert report['mae_uint8']<1 and report['p95_uint8']<=2
finally:
 client.simPause(was_paused);editor('result=diversity_suspend('+repr(was_suspended)+')')

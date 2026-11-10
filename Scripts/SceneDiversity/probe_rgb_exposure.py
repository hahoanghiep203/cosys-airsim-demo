"""Compare three RGB ISO presets at fixed viewpoints in the owned PIE session."""
import io
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Scripts/RouteCaptureDemo'))
from editor_command import editor
import airsim

output=ROOT/'Saved/SceneDiversity/CameraExposure_20261023/f14_corrected'
output.mkdir(parents=True,exist_ok=True)
views=json.loads((ROOT/'Config/SceneDiversity/viewpoints.json').read_text())['views']
profile=json.loads((ROOT/'Config/SceneDiversity/rgb_camera.json').read_text())
client=airsim.VehicleClient(ip='127.0.0.1',port=41471,timeout_value=180)
editor("exec((ROOT/'Scripts/SceneDiversity/rgb_camera.py').read_text(),globals(),globals()); result={'reloaded':True}")
deadline=time.monotonic()+240
while time.monotonic()<deadline:
 state=editor('result=diversity_snapshot()')
 if state.get('ready'):break
 time.sleep(.5)
else:raise TimeoutError('Camera runtime not ready')
editor('result=diversity_suspend(True)')
client.simPause(True)
records=[]
sheet=Image.new('RGB',(960,3*215),'#202124')
draw=ImageDraw.Draw(sheet)
for vi,index in enumerate((0,6,13)):
 view=views[index]
 for ii,iso in enumerate((1600,6400,25600)):
  preset=dict(profile,iso=iso)
  code="DIVERSITY_STATE['rgb_camera_profile']=apply_rgb_camera_profile("+repr(preset)+"); result=diversity_set_view("+repr(view['position_cm'])+','+repr(view['target_cm'])+',True)'
  applied=editor(code)
  client.simPause(False)
  start=time.monotonic()
  while True:
   tick=editor("result={'tick':DIVERSITY_STATE['tick']}")['tick']
   if tick>=applied['tick']+8 and time.monotonic()-start>1:break
   time.sleep(.15)
  client.simPause(True)
  response=airsim.ImageResponse.from_msgpack(client.client.call('simGetImages',[airsim.ImageRequest('0',0,False,True)],'EveningSample')[0])
  assert response.width==1280 and response.height==720
  im=Image.open(io.BytesIO(response.image_data_uint8)).convert('RGB')
  name=f'{index:03d}_iso{iso}.png'
  im.save(output/name)
  a=np.asarray(im.convert('L'),dtype=float)
  records.append(dict(view=view['id'],iso=iso,file=name,mean=float(a.mean()),p50=float(np.percentile(a,50)),
   fraction_le8=float((a<=8).mean()),fraction_ge250=float((a>=250).mean())))
  thumb=im.resize((320,180))
  sheet.paste(thumb,(ii*320,vi*215+30))
  draw.text((ii*320+4,vi*215+4),f"{view['id']} ISO {iso}",fill='white')
  print(json.dumps(records[-1]),flush=True)
(output/'iso_probe.json').write_text(json.dumps(records,indent=2))
sheet.save(output/'iso_comparison.jpg',quality=94)
print(json.dumps({'output':str(output)}))

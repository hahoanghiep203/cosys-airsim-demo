"""Save a genuinely paired RGB/IR sample using a brief simulation freeze."""
import json
import time
from pathlib import Path
import airsim
import msgpack
import msgpackrpc.transport.tcp as rpc_tcp
from PIL import Image
import io
root=Path(__file__).resolve().parents[2]
output=root/'Saved/EveningSample';output.mkdir(parents=True,exist_ok=True)
original_init=rpc_tcp.BaseSocket.__init__
def large_frame_socket(self,stream,encodings):
    original_init(self,stream,encodings)
    self._unpacker=msgpack.Unpacker(encoding=encodings[1],max_buffer_size=128*1024*1024,max_bin_len=64*1024*1024,max_str_len=64*1024*1024,max_array_len=4*1024*1024)
rpc_tcp.BaseSocket.__init__=large_frame_socket
client=airsim.VehicleClient(ip='127.0.0.1',port=41471,timeout_value=180)
client.simPause(True)
try:
    raw=client.client.call('simGetImages',[airsim.ImageRequest('0',kind,False,True) for kind in (0,12)],'EveningSample')
    records=[]
    for label,data in zip(('rgb','ir'),raw):
        response=airsim.ImageResponse.from_msgpack(data)
        assert not response.message and (response.width,response.height)==(1280,720),response.message
        frame=Image.open(io.BytesIO(response.image_data_uint8)).convert('RGB')
        frame.save(output/('sample_'+label+'.png'))
        records.append({'channel':label,'size':[response.width,response.height],'camera_position':str(response.camera_position),'camera_orientation':str(response.camera_orientation),'time_stamp':response.time_stamp})
    (output/'capture_pair.json').write_text(json.dumps(records,indent=2))
    print(json.dumps(records,indent=2))
finally:
    client.simPause(False)

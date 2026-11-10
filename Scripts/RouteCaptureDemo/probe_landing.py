"""Exercise native Land Here after a run, then audit acknowledgement and handoff."""
import argparse
import json
from pathlib import Path
import time

import airsim

from editor_command import editor,ROOT
from build_evidence_report import write_json

def probe(result_file,output):
    result=json.loads(Path(result_file).read_text(encoding='utf-8'))
    run=Path(result['run_dir'])
    recovery=run/'recovery.json'
    baseline=recovery.stat().st_mtime_ns if recovery.exists() else -1
    editor('mission_route.land();result=True')
    deadline=time.monotonic()+80
    while time.monotonic()<deadline:
        try:
            if recovery.stat().st_mtime_ns>baseline:
                acknowledgement=json.loads(recovery.read_text(encoding='utf-8'))
                break
        except (OSError,ValueError):
            pass
        time.sleep(.2)
    else:
        raise TimeoutError('Independent landing did not acknowledge within its watchdog')
    time.sleep(.5)
    statuses=[]
    for _ in range(3):
        statuses.append(editor("result=mission_route.get_editor_property('status')"))
        time.sleep(.5)
    client=airsim.MultirotorClient(ip='127.0.0.1',port=41469,timeout_value=5)
    state=client.getMultirotorState(vehicle_name='RouteDrone')
    api_owned=client.isApiControlEnabled(vehicle_name='RouteDrone')
    data={'run_dir':str(run),'recovery':acknowledgement,'native_status_across_ticks':statuses,
          'landed_state':int(state.landed_state),'api_control_enabled':api_owned,
          'speed_mps':state.kinematics_estimated.linear_velocity.get_length()}
    destination=ROOT/output
    destination.parent.mkdir(parents=True,exist_ok=True)
    write_json(destination,data)
    print(json.dumps(data,indent=2))
    assert acknowledgement['landed'] and not acknowledgement['errors']
    assert state.landed_state==airsim.LandedState.Landed and not api_owned
    assert all('Landing acknowledged' in status for status in statuses)
    return data

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('result')
    parser.add_argument('--output',default='Saved/RouteCaptureReview/Deliverables/landing_probe.json')
    args=parser.parse_args()
    probe(args.result,args.output)

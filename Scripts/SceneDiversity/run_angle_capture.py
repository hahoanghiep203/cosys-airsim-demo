"""One manually invoked batch; use only an editor already showing the combined map."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

from capture_angles import ROOT, MAP, SCENE, editor


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--count',type=int)
    args=parser.parse_args()
    marker=json.loads((ROOT/'Saved/RouteCaptureReview/editor_ready.json').read_text())
    if Path(marker['project']).resolve()!=ROOT.resolve():
        raise RuntimeError('The editor bridge belongs to another project')
    status=editor('''
def _angles_prepare_session():
 system=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
 world=system.get_game_world() or system.get_editor_world()
 assert 'ThermalDiversity_05_CombinedEnvironment.' in world.get_path_name(), 'Open the Combined Environment map first'
 if not system.get_game_world():
  exec((ROOT/'Scripts/SceneDiversity/runtime.py').read_text(),globals(),globals())
  diversity_install()
  unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_begin_play()
 return {'pid':__import__('os').getpid()}
result=_angles_prepare_session()
del _angles_prepare_session
''',timeout=180)
    if status['pid']!=marker['pid']:
        raise RuntimeError('Editor PID differs from the current bridge marker')
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        state=editor('result=diversity_snapshot()')
        if state.get('ready') and state.get('id')==SCENE:
            break
        time.sleep(.5)
    else:
        raise TimeoutError('Combined thermal runtime did not become ready')
    output=(args.output or ROOT/'Saved/SceneDiversity/viewpoint_runs'/datetime.now().strftime('%Y%m%d_%H%M%S')).resolve()
    command=[sys.executable,str(ROOT/'Scripts/SceneDiversity/capture_angles.py'),'--output',str(output)]
    if args.count is not None:
        command+=['--count',str(args.count)]
    subprocess.run(command,check=True)
    subprocess.run([sys.executable,str(ROOT/'Scripts/SceneDiversity/audit_angles.py'),str(output)],check=True)
    print('Saved independent RGB/IR viewpoints to: '+str(output))


if __name__=='__main__':
    main()

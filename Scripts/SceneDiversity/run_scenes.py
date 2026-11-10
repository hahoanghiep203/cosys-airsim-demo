"""Collect configured routes in an already-owned test editor. Does not launch or close editors."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Scripts/RouteCaptureDemo'))
from editor_command import editor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scene', help='One configured scene id; omit for all four')
    args = parser.parse_args()
    scenes = json.loads((ROOT / 'Config/SceneDiversity/scenes.json').read_text())['scenes']
    if args.scene:
        scenes = [s for s in scenes if s['id'] == args.scene]
        assert scenes, 'Unknown scene'
        if scenes[0].get('capture_mode')=='independent_viewpoints':
            raise ValueError('Use run_angle_capture.py for the combined environment')
    else:
        scenes=[s for s in scenes if s.get('capture_mode')!='independent_viewpoints']
        if not scenes:
            raise RuntimeError('Individual scene maps were archived; use run_angle_capture.py for the combined environment.')
    for scene in scenes:
        print('LOAD ' + scene['id'], flush=True)
        editor("""world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
if world:unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()
result=True
""")
        deadline = time.monotonic() + 60
        while editor('result=bool(unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world())'):
            if time.monotonic() > deadline:
                raise TimeoutError('PIE did not end; refuse map switch')
            time.sleep(.2)
        editor("assert unreal.EditorLevelLibrary.load_level(" + repr(scene['map']) + ")\n"
               "exec((ROOT/'Scripts/ScenePerformance/profile.py').read_text(encoding='utf-8-sig'))\n"
               "scene_apply('balanced')\n"
               "if 'diversity_snapshot' not in globals():\n"
               " exec((ROOT/'Scripts/SceneDiversity/runtime.py').read_text(encoding='utf-8-sig'))\n"
               " diversity_install()\nresult=True", timeout=600)
        subprocess.run([sys.executable, str(ROOT / 'Scripts/SceneDiversity/capture_routes.py'),
                        '--scene', scene['id']], check=True, cwd=ROOT)
        editor((ROOT / 'Scripts/SceneDiversity/validate_live.py').read_text(), timeout=240)
    if not args.scene:
        subprocess.run([sys.executable, str(ROOT / 'Scripts/SceneDiversity/audit_captures.py')], check=True, cwd=ROOT)


if __name__ == '__main__':
    main()

import json,sys,time
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'RouteCaptureDemo'))
from editor_command import editor,ROOT
output=ROOT/'Saved/ScenePerformance'/('render_benchmark_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
output.mkdir(parents=True,exist_ok=False)
editor((ROOT/'Scripts/ScenePerformance/prepare_benchmark.py').read_text())
for label,profile in [('render_baseline_1','baseline'),('render_balanced_1','balanced'),('render_baseline_2','baseline'),('render_balanced_2','balanced')]:
    editor(f'result=scene_apply({profile!r})')
    time.sleep(3)
    editor(f'''
scene_render_label={label!r}
scene_render_output=Path({str(output)!r})
scene_render_samples=[]
scene_render_busy=False

def scene_render_tick(delta):
    global scene_render_busy
    if scene_render_busy:return
    scene_render_busy=True
    try:
        started=time.perf_counter()
        scene_probe_component.capture_scene()
        pixel=unreal.RenderingLibrary.read_render_target_pixel(scene_world(),scene_probe_target,480,270)
        scene_render_samples.append((time.perf_counter()-started)*1000)
        if len(scene_render_samples)<35:return
        unreal.unregister_slate_post_tick_callback(scene_render_callback)
        samples=scene_render_samples[5:]
        ordered=sorted(samples)
        report={{'label':scene_render_label,'measurement':'explicit 960x540 SceneCapture render plus synchronous one-pixel GPU readback wall ms, excluding PNG encoding; not drone-flight FPS','warmup_samples':5,'samples':len(samples),'mean_ms':sum(samples)/len(samples),'median_ms':ordered[len(ordered)//2],'p95_ms':ordered[int(len(ordered)*.95)],'samples_ms':samples,'pixel':str(pixel)}}
        (scene_render_output/(scene_render_label+'.json')).write_text(json.dumps(report,indent=2))
    finally:scene_render_busy=False
scene_render_callback=unreal.register_slate_post_tick_callback(scene_render_tick)
result=True
''')
    path=output/(label+'.json');deadline=time.monotonic()+120
    while not path.exists():
        if time.monotonic()>deadline:raise TimeoutError(label)
        time.sleep(.5)
    print(json.dumps({k:v for k,v in json.loads(path.read_text()).items() if k!='samples_ms'}),flush=True)
editor("scene_apply('baseline');unreal.get_editor_subsystem(unreal.EditorActorSubsystem).destroy_actor(scene_probe_actor);result=True")
print('Evidence: '+str(output),flush=True)

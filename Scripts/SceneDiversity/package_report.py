"""Publish actual scene/capture evidence and an RGB/IR contact sheet."""
import json
import shutil
import csv
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = ROOT / 'Saved/SceneDiversity'
    output = ROOT / 'Docs/SceneDiversity'
    output.mkdir(parents=True, exist_ok=True)
    scenes = json.loads((ROOT / 'Config/SceneDiversity/scenes.json').read_text())['scenes']
    scenes = [s for s in scenes if s.get('capture_mode') != 'independent_viewpoints']
    audit = json.loads((source / 'capture_audit.json').read_text())
    assert audit['status'] == 'passed' and audit['pairs'] == 50 and audit.get('surface_checks_verified')
    automation = json.loads((source / 'Automation/index.json').read_text(encoding='utf-8-sig'))
    assert automation['succeeded'] == 16 and automation['failed'] == 0
    performance = json.loads((ROOT / 'Saved/ProjectMaintenance/diversity_optimized_final_720_20261023.json').read_text())
    engine = json.loads((ROOT / 'Saved/ProjectMaintenance/engine_frame_summary.json').read_text())[-1]
    sheet = Image.new('RGB', (1280, 4 * 400 + 42), (19, 22, 29))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 22)
    except OSError:
        font = ImageFont.load_default()
    draw.text((15, 8), 'Actual 720p captures  |  RGB left   /   ThermalIR right', font=font, fill='white')
    summaries = []
    dataset = source / 'thermalgen50'
    for name in ('rgb', 'ir', 'metadata'):
        (dataset / name).mkdir(parents=True, exist_ok=True)
    pairs_csv = []
    movie_frames = source / 'movie_frames'
    movie_frames.mkdir(exist_ok=True)
    movie_index = 0
    for row, scene in enumerate(scenes):
        directory = source / 'captures' / scene['id']
        manifest = json.loads((directory / 'manifest.json').read_text())
        for sample in manifest['pairs']:
            basename = scene['id'] + '_' + f"{sample['index']:03d}"
            for channel in ('rgb', 'ir'):
                shutil.copy2(directory / sample['images'][channel]['file'], dataset / channel / (basename + '.png'))
            shutil.copy2(directory / f"{sample['index']:03d}_metadata.json", dataset / 'metadata' / (basename + '.json'))
            pairs_csv.append({'sample_id': basename, 'scene': scene['id'], 'rgb': 'rgb/' + basename + '.png',
                              'ir': 'ir/' + basename + '.png', 'metadata': 'metadata/' + basename + '.json'})
            preview = Image.new('RGB', (1280, 400), (19, 22, 29))
            ImageDraw.Draw(preview).text((15, 7), scene['id'] + ' | saved route pair ' + str(sample['index'] + 1)
                                        + ' | RGB / IR | 4 pairs/s playback', font=font, fill='white')
            for column, channel in enumerate(('rgb', 'ir')):
                with Image.open(directory / sample['images'][channel]['file']) as image:
                    preview.paste(image.convert('RGB').resize((640, 360), Image.Resampling.LANCZOS), (column * 640, 40))
            preview.save(movie_frames / f'{movie_index:04d}.png')
            movie_index += 1
        pair = manifest['pairs'][len(manifest['pairs']) // 2]
        y = 42 + row * 400
        draw.text((15, y + 5), scene['id'] + '  |  ' + str(scene['captures']) + ' pairs', font=font, fill=(220, 228, 240))
        for column, channel in enumerate(('rgb', 'ir')):
            file = directory / pair['images'][channel]['file']
            with Image.open(file) as frame:
                sheet.paste(frame.convert('RGB').resize((640, 360), Image.Resampling.LANCZOS), (column * 640, y + 40))
            shutil.copy2(file, output / (scene['id'] + '_' + channel + '.png'))
        for suffix in ('_build.json', '_surface_checks.json'):
            shutil.copy2(source / (scene['id'] + suffix), output / (scene['id'] + suffix))
        shutil.copy2(directory / 'manifest.json', output / (scene['id'] + '_manifest.json'))
        surfaces = json.loads((source / (scene['id'] + '_surface_checks.json')).read_text())
        summaries.append({'id': scene['id'], 'new_objects': len(json.loads((source / (scene['id'] + '_build.json')).read_text())['new_objects']),
                          'vehicles': [v['model'] for v in scene['vehicles']], 'source_count': surfaces['source_count'],
                          'ambient_k': scene['ambient_k'], 'lamp_kelvin': scene['lamp_kelvin'],
                          'counter_k': scene['counter_k'], 'pairs': len(manifest['pairs'])})
    sheet.save(output / 'overview.png')
    assert len(pairs_csv) == 50 and movie_index == 50
    with (dataset / 'pairs.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(pairs_csv[0]))
        writer.writeheader(); writer.writerows(pairs_csv)
    (dataset / 'README.txt').write_text('50 paired actual synthetic samples at 1280x720. RGB and IR use matching basenames; pairs.csv supplies scene groups and metadata paths. IR is an 8-bit display image, not Kelvin labels. Split by scene/route to avoid neighbouring-frame leakage. Rejected diagnostic captures are excluded. No model training performed.\n')
    subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-y', '-loglevel', 'error', '-framerate', '4',
                    '-i', str(movie_frames / '%04d.png'), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-crf', '20', '-movflags', '+faststart', str(output / 'route_preview.mp4')], check=True)
    shutil.copy2(source / 'capture_audit.json', output / 'capture_audit.json')
    shutil.copy2(source / 'vehicle_assets.json', output / 'vehicle_assets.json')
    shutil.copy2(source / 'rim_probes.json', output / 'rim_probes.json')
    report = {'capture_audit': audit, 'scene_summary': summaries,
              'automation': {'succeeded': automation['succeeded'], 'failed': automation['failed'],
                             'moving_tire_test': next(t for t in automation['tests'] if 'MovingAttachedTireField' in t['fullTestPath'])},
              'performance': {k: v for k, v in performance.items() if k not in ('world_deltas', 'wall_intervals')},
              'engine': engine, 'capture_root': str(source / 'captures')}
    (output / 'validation.json').write_text(json.dumps(report, indent=2))
    cards = ''.join('<section><h2>' + s['id'].replace('_', ' ') + '</h2><div class="pair"><img alt="RGB" src="'
                    + s['id'] + '_rgb.png"><img alt="IR" src="' + s['id'] + '_ir.png"></div></section>' for s in scenes)
    (output / 'INDEX.html').write_text('''<!doctype html><meta charset="utf-8"><title>Four thermal scenes</title>
<style>body{margin:32px auto;max-width:1320px;padding:0 20px;background:#13161d;color:#edf1f8;font:16px system-ui}h1{font-size:30px}h2{font-size:18px}section{margin:28px 0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}img,video{width:100%;border-radius:8px}a{color:#88d5ed}p{max-width:900px;line-height:1.5}</style>
<h1>Four thermal scenes</h1><p>50 actual RGB/IR pairs at 1280 × 720. Left: low-light RGB. Right: thermal IR. These are synthetic demonstration temperatures; images are not calibrated Kelvin labels.</p>
<p><a href="README.md">How to open and edit</a> · <a href="VALIDATION.md">Measured validation</a> · <a href="../../Saved/SceneDiversity/thermalgen50/pairs.csv">Paired dataset index</a></p>
<video controls preload="metadata" src="route_preview.mp4"></video><p>Playback shows the saved samples at four pairs per second. It is a route preview, not real-time flight footage.</p>''' + cards, encoding='utf-8')
    summary = engine['summary']['FrameTime']
    (output / 'VALIDATION.md').write_text(f'''# Verified four-scene collection — 2026-10-23

Four separate maps contain different object arrangements and dusk/blue-hour/night/moonlit presets. Existing licensed assets are reused. Added vehicles: hatchback, SUV, pickup, sports car and box truck. All five have model-specific hood/front-panel, two headlight and four tire child sources (six tires on the truck). New objects per map are in validation.json; inherited cafe props are additional. Editable route splines are editor-only and excluded from camera images.

**50 paired samples / 100 PNG images at 1280 x 720** are in `Saved/SceneDiversity/captures`. Per-scene allocation: 13 + 13 + 12 + 12. Every accepted pair has matching reported RGB/IR poses and timestamps, a verified frozen scene, actual camera translation and measured driving-car displacement. The camera travels 8.3066 m per route; cars travel approximately 9–11 m between first/last samples. Actual source settings and vehicle transforms accompany every pair. All accepted IR images are unique. This is controlled kinematic camera/vehicle motion, not a physical drone flight or wheel-rotation simulation.

Native **16/16 thermal automation tests passed**, including attachment translation/rotation, GPU receiver matrices, annulus/bore exclusion and residual cooling. Actual scene probes confirm tire source attachment errors below 0.1 cm, warm driving rubber, ambient parked rubber and ambient wheel hubs/rims. Sports rim probes use actual mesh vertices, avoiding an empty-space rear AABB-face probe that read the road. The sports hood volume was reduced to 12 cm contact depth and body material index1 so it cannot directly heat rim material. Two affected batches were rejected and recaptured. The older constant-60 C parked tire preset is replaced by operating states in these scenes.

The original Showcase, user's CoordinateCrop and previous EveningSample map hashes match pre-build values. Decorative water/translucent planes received no sources. No imported people/dog meshes, purchases, native engine transform rewrite, commit or push.

RGB initially inherited distortion post-process materials that produced a fixed border and did not match the geometry-based IR projection. That batch was rejected. The dataset runtime now removes those distortion blendables using independent copied post-process structs and non-notifying property updates. An earlier editor-notifying live camera change reconstructed camera internals and crashed only the owned test editor; the fresh corrected editor completed all four routes. Raw rejected/failed outputs remain outside the accepted capture directory for diagnosis.

The final moving four-vehicle scene, both outputs active at720p for {performance['seconds']:.3f}s, measured **{summary['fps']:.2f} FPS** mean engine rate and **{performance['ir_dispatch_hz']:.2f} Hz** actual IR dispatch. Engine frame time mean {summary['mean']:.2f}ms, p95 {summary['p95']:.2f}ms, maximum {summary['max']:.2f}ms; {summary['over_100ms']} frames exceeded100ms and {summary['over_500ms']} exceeded500ms. This is an editor PIE benchmark on this workstation, not packaged-flight FPS or saved-image throughput. The 30Hz preview target is not claimed as achieved. More heat/vehicle simulation is CPU-bound; the GPU average timing is separately recorded in validation.json. Startup duplicates the large original map and uses substantial RAM; local inference stayed unloaded.

These thermal presets and 8-bit display values are demonstrations, not calibrated radiometric Kelvin labels. In cold-soaked scenes, a vehicle at nearly the same temperature as the road can have very low IR contrast. This is intentional rather than guaranteed object detectability. No class/instance mask bundle or ThermalGen model training was performed.

Advisers: invoked astra-team; Antigravity gemini-4-argon-medium reviewed the scene/validation concept. After the user explicitly permitted all agent types, one native Sol High worker added the moving tire regression and drafted the runtime/capture tools. The coordinator integrated, repaired and live-verified them. Local inference was not loaded alongside Unreal.
''', encoding='utf-8')
    print(json.dumps({'overview': str(output / 'overview.png'), 'pairs': 50, 'native_tests': 16,
                      'engine_fps': summary['fps'], 'ir_dispatch_hz': performance['ir_dispatch_hz']}))


if __name__ == '__main__':
    main()

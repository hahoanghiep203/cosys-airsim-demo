"""Audit all four actual capture manifests; never infer completion from file counts alone."""
import hashlib
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def audit():
    scenes = json.loads((ROOT / 'Config/SceneDiversity/scenes.json').read_text())['scenes']
    scenes = [s for s in scenes if s.get('capture_mode') != 'independent_viewpoints']
    assert len(scenes) == 4 and len({s['map'] for s in scenes}) == 4
    rows = []
    for scene in scenes:
        directory = ROOT / 'Saved/SceneDiversity/captures' / scene['id']
        manifest = json.loads((directory / 'manifest.json').read_text())
        assert manifest['status'] == 'passed' and len(manifest['pairs']) == scene['captures']
        assert manifest['camera_translation_m'] > .1
        assert manifest['driving_displacement_cm'] and all(d > 1 for d in manifest['driving_displacement_cm'].values())
        hashes = set()
        for pair in manifest['pairs']:
            assert pair['frozen_scene_verified'] and pair['timestamp_delta_ns'] == 0
            for channel in ('rgb', 'ir'):
                file = directory / pair['images'][channel]['file']
                with Image.open(file) as image:
                    assert image.size == (1280, 720)
                    image.verify()
                if channel == 'ir':
                    hashes.add(hashlib.sha256(file.read_bytes()).hexdigest())
            for car in pair['snapshot']['vehicles']:
                tires = [s for s in car['sources'] if 'tire' in s['name'].lower()]
                assert len(tires) == (6 if car['model'] == 'Truck_Box' else 4)
                if car['state'] == 'parked':
                    assert all(not t['enabled'] and abs(t['temperature_k'] - scene['ambient_k']) < .01 for t in tires)
                else:
                    assert all(t['enabled'] and scene['ambient_k'] < t['temperature_k'] < 333.15 for t in tires)
        assert len(hashes) == scene['captures'], 'Duplicate IR images along route'
        build = json.loads((ROOT / 'Saved/SceneDiversity' / (scene['id'] + '_build.json')).read_text())
        assert build['protected_maps_unchanged'] and len(build['new_objects']) >= 10
        surfaces = json.loads((ROOT / 'Saved/SceneDiversity' / (scene['id'] + '_surface_checks.json')).read_text())
        for vehicle in surfaces['vehicles']:
            for tire in vehicle['tires']:
                assert tire['source_attachment_error_cm'] < .1
                assert abs(tire['rim_surface_k'] - scene['ambient_k']) < 1, ('Rim heated', scene['id'], vehicle['model'], tire)
                if vehicle['state'] == 'parked':
                    assert max(tire['tread_surface_k']) <= scene['ambient_k'] + 1
                elif vehicle['state'] == 'driving':
                    assert max(tire['tread_surface_k']) > scene['ambient_k'] + 1, ('Driving rubber not warm', vehicle, tire)
        rows.append({'id': scene['id'], 'pairs': len(manifest['pairs']), 'unique_ir': len(hashes),
                     'camera_translation_m': manifest['camera_translation_m'],
                     'driving_displacement_cm': manifest['driving_displacement_cm']})
    assert sum(row['pairs'] for row in rows) == 50
    protected_file = ROOT / 'Saved/SceneDiversity/protected_maps.json'
    if not protected_file.exists():
        protected_file = ROOT / 'Config/SceneDiversity/protected_maps.json'
    protected = json.loads(protected_file.read_text())
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in protected.items())
    report = {'status': 'passed', 'pairs': 50, 'images': 100, 'scenes': rows, 'protected_maps_unchanged': True,
              'surface_checks_verified': True, 'scope': 'paired images plus actual attached rubber/rim surface probes'}
    (ROOT / 'Saved/SceneDiversity/capture_audit.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    audit()

"""Audit independent viewpoint manifests and PNGs without contacting Unreal."""
import argparse
import hashlib
import json
import math
from pathlib import Path

SCENE = '05_combined_environment'
MAP = '/Game/CityPark/Maps/ThermalDiversity_05_CombinedEnvironment'


def _distance(a, b):
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


def _frozen(snapshot):
    return {key: snapshot[key] for key in ('id', 'world', 'elapsed', 'vehicles', 'all_thermal_sources')}


def _pose(image):
    pose = image['pose']
    position, orientation = pose['position_m'], pose['orientation_xyzw']
    if len(position) != 3 or len(orientation) != 4 or not all(
            isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x) for x in position + orientation):
        raise ValueError('Invalid actual sensor pose')
    if abs(sum(x*x for x in orientation) - 1) > .002:
        raise ValueError('Sensor quaternion must be normalized')
    return position, orientation


def audit(manifest_path, expected_count=None):
    from PIL import Image, ImageDraw, ImageStat
    manifest_path = Path(manifest_path).resolve()
    directory = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    errors, rows, positions, orientations, actual_poses, ids = [], [], [], [], [], set()
    origins=[];direction_errors=[];zone_angles={}
    def require(condition, message):
        if not condition:
            errors.append(message)
    expected = expected_count if expected_count is not None else manifest.get('expected_count', 50)
    require(isinstance(expected, int) and not isinstance(expected, bool) and expected > 0, 'Invalid expected_count')
    require(manifest.get('status') == 'passed', 'Capture status must be passed')
    require(manifest.get('capture_mode') == 'independent_viewpoints', 'Wrong capture_mode')
    require(manifest.get('scene') == SCENE and manifest.get('map') == MAP, 'Wrong scene or map')
    require(not manifest.get('restoration_errors'), 'Capture reported restoration errors')
    pairs = manifest.get('pairs', [])
    require(isinstance(pairs, list) and len(pairs) == expected, 'Pair count differs from expected_count')
    require(manifest.get('expected_count') == expected, 'Manifest expected_count differs from requested count')
    baseline = manifest.get('frozen_baseline', {})
    try:
        reference = _frozen(baseline)
        require(baseline.get('id') == SCENE and MAP.rsplit('/', 1)[-1] in baseline.get('world', ''), 'Baseline scene mismatch')
        require(bool(baseline.get('suspended')), 'Baseline was not suspended')
        require(bool(baseline['vehicles']) and bool(baseline['all_thermal_sources']), 'Baseline source state is empty')
        require(math.isfinite(baseline['elapsed']), 'Nonfinite baseline elapsed')
    except (KeyError, TypeError, ValueError) as error:
        errors.append('Invalid frozen baseline: ' + str(error))
        reference = None
    if not isinstance(pairs, list):
        pairs = []
    hashes = {'rgb': set(), 'ir': set()}
    for index, pair in enumerate(pairs):
        prefix = f'Pair {index}: '
        try:
            identity = pair['view_id']
            require(isinstance(identity, str) and bool(identity.strip()) and identity not in ids, prefix + 'missing/duplicate view id')
            ids.add(identity)
            require(pair.get('index') == index, prefix + 'index mismatch')
            require(isinstance(pair.get('zone'), str) and bool(pair['zone'].strip()), prefix + 'missing zone')
            for key in ('requested_camera_cm', 'requested_target_cm'):
                require(len(pair[key]) == 3 and all(math.isfinite(x) for x in pair[key]), prefix + 'invalid ' + key)
            require(_distance(pair['requested_camera_cm'], pair['requested_target_cm']) >= 1, prefix + 'empty view direction')
            require(pair.get('settled_ticks', 0) >= 5, prefix + 'fewer than five settled ticks')
            require(pair.get('settle_wall_seconds',0)>=.25,prefix+'settle time below 0.25 seconds')
            collision = pair.get('collision_check', {})
            require(collision.get('blocked') is False and collision.get('radius_cm', 0) >= 15,
                    prefix + 'missing or failed collision clearance')
            require(pair.get('frozen_scene_verified') is True, prefix + 'missing frozen verification')
            for key in ('snapshot', 'after_snapshot'):
                snapshot = pair[key]
                require(snapshot.get('suspended') is True and _frozen(snapshot) == reference,
                        prefix + key + ' differs from baseline frozen source state')
            rgb, ir = pair['images']['rgb'], pair['images']['ir']
            p, q = _pose(rgb)
            origins.append([a-b*100 for a,b in zip(pair['requested_camera_cm'],(p[0],p[1],-p[2]))])
            x,y,z,w=q
            forward=[1-2*(y*y+z*z),2*(x*y+w*z),-2*(x*z-w*y)]
            requested=[b-a for a,b in zip(pair['requested_camera_cm'],pair['requested_target_cm'])]
            length=math.sqrt(sum(v*v for v in requested))
            dot=sum(a*b/length for a,b in zip(forward,requested))
            direction_error=math.degrees(math.acos(max(-1,min(1,dot))))
            direction_errors.append(direction_error)
            require(direction_error<.1,prefix+'actual orientation does not aim at requested target')
            zone_angles.setdefault(pair['zone'],set()).add(int((pair['azimuth_deg']%360)//45))
            ip, iq = _pose(ir)
            require(_distance(p, ip) <= 1e-4 and min(_distance(q, iq), _distance(q, [-x for x in iq])) <= 1e-4,
                    prefix + 'RGB/IR pose mismatch')
            require(isinstance(rgb['time_stamp'], int) and rgb['time_stamp'] > 0 and rgb['time_stamp'] == ir['time_stamp'],
                    prefix + 'RGB/IR timestamps must match and be positive')
            require(pair.get('timestamp_delta_ns') == abs(rgb['time_stamp'] - ir['time_stamp']) == 0,
                    prefix + 'invalid timestamp delta')
            require(not any(_distance(p, oldp) < 1e-4 and min(_distance(q, oldq), _distance(q, [-x for x in oldq])) < 1e-4
                            for oldp, oldq in actual_poses), prefix + 'duplicate actual viewpoint')
            actual_poses.append((p, q))
            positions.append(p)
            orientations.append(q)
            thumbnails = []
            for channel, image in (('rgb', rgb), ('ir', ir)):
                image_path = (directory / image['file']).resolve()
                require(image_path.parent == directory and image_path.suffix.lower() == '.png', prefix + channel + ' image path outside run folder')
                if image_path.parent != directory:
                    continue
                digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
                require(image.get('sha256') == digest, prefix + channel + ' SHA256 mismatch')
                require(digest not in hashes[channel], prefix + channel + ' duplicates a previous image')
                hashes[channel].add(digest)
                with Image.open(image_path) as frame:
                    frame.load()
                    require(frame.format == 'PNG' and frame.size == (1280, 720) and image.get('size') == [1280, 720],
                            prefix + channel + ' must be PNG 1280x720')
                    rgb_frame = frame.convert('RGB')
                    require(max(ImageStat.Stat(rgb_frame).var) > .01, prefix + channel + ' image is empty/constant')
                    rgb_frame.thumbnail((192, 108))
                    thumbnails.append(rgb_frame.copy())
            if len(thumbnails) == 2:
                rows.append((identity, pair['zone'], thumbnails))
        except (KeyError, TypeError, ValueError, OSError) as error:
            errors.append(prefix + str(error))
    unique_positions = {tuple(round(x, 4) for x in p) for p in positions}
    unique_orientations = set()
    for q in orientations:
        sign = 1 if next((x for x in reversed(q) if abs(x) > 1e-8), 1) >= 0 else -1
        unique_orientations.add(tuple(round(sign*x, 5) for x in q))
    if len(pairs) > 1:
        require(len(unique_positions) > 1, 'Actual camera position did not vary')
        require(len(unique_orientations) > 1, 'Actual camera orientation did not vary')
    origin_spread=max((_distance(p,origins[0]) for p in origins),default=0)
    require(origin_spread<2,'Actual camera translations differ from requested viewpoints')
    if expected==50:
        require(set(zone_angles)=={'cafe','service','market','parking'},'Missing environment zone')
        require(all(len(bins)>=4 for bins in zone_angles.values()),'Insufficient azimuth diversity within a zone')
    # Five columns, each with a legible paired RGB/IR tile; 50 pairs => ten rows.
    if rows:
        columns, tile_width, tile_height = 5, 384, 138
        sheet = Image.new('RGB', (columns * tile_width, math.ceil(len(rows) / columns) * tile_height), '#202124')
        draw = ImageDraw.Draw(sheet)
        for index, (identity, zone, thumbnails) in enumerate(rows):
            x, y = index % columns * tile_width, index // columns * tile_height
            draw.text((x + 4, y + 3), (identity + ' | ' + zone)[:58], fill='white')
            draw.text((x + 4, y + 16), 'RGB', fill='#bbbbbb')
            draw.text((x + 196, y + 16), 'IR', fill='#bbbbbb')
            sheet.paste(thumbnails[0], (x, y + 30))
            sheet.paste(thumbnails[1], (x + 192, y + 30))
        sheet.save(directory / 'contact_sheet.jpg', quality=90)
    report = {'status': 'passed' if not errors else 'failed', 'scene': manifest.get('scene'), 'map': manifest.get('map'),
              'capture_mode': manifest.get('capture_mode'), 'expected_count': expected, 'pair_count': len(pairs),
              'unique_actual_positions': len(unique_positions), 'unique_actual_orientations': len(unique_orientations),
              'unique_image_hashes': {key: len(value) for key, value in hashes.items()},
              'camera_origin_spread_cm':origin_spread,'maximum_aim_error_deg':max(direction_errors,default=0),
              'azimuth_bins_per_zone':{k:len(v) for k,v in zone_angles.items()},
              'contact_sheet': 'contact_sheet.jpg' if rows else None, 'errors': errors}
    (directory / 'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path, help='manifest.json or its capture directory')
    parser.add_argument('--expected-count', type=int)
    args = parser.parse_args()
    manifest_path = args.manifest / 'manifest.json' if args.manifest.is_dir() else args.manifest
    report = audit(manifest_path, args.expected_count)
    print(json.dumps(report, indent=2))
    if report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()

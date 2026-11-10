"""Conservative package audit. No saves, deletes or moves. Run with -run=pythonscript."""
import json
from pathlib import Path
import unreal

root = Path(unreal.Paths.project_dir()).resolve()
out = root / 'Saved/ProjectMaintenance'
out.mkdir(parents=True, exist_ok=True)
registry = unreal.AssetRegistryHelpers.get_asset_registry()
registry.search_all_assets(True)
registry.wait_for_completion()
assets = registry.get_assets_by_path('/Game', recursive=True)
packages = {str(a.package_name) for a in assets}
maps = {str(a.package_name) for a in assets if str(a.asset_class_path.asset_name) == 'World'}
# Keep every map, future vehicle library, thermal authored assets and developer work.
roots = maps | {p for p in packages if p.startswith(('/Game/VehicleVarietyPack/', '/Game/Thermal/', '/Game/RouteCapture/', '/Game/Developers/'))}
dynamic = set()
import re
for directory in ('Config', 'Scripts', 'Source', 'Plugins'):
    for file in (root / directory).rglob('*'):
        if file.suffix.lower() not in ('.json', '.ini', '.py', '.cpp', '.h', '.cs', '.uplugin'): continue
        if any(p in file.parts for p in ('Intermediate', 'Binaries', '__pycache__')): continue
        try:
            for match in re.findall(r'/Game/[A-Za-z0-9_/]+', file.read_text(encoding='utf-8', errors='ignore')):
                if match in packages: dynamic.add(match)
        except OSError: pass
roots |= dynamic
roots |= {str(a.package_name) for a in registry.get_all_assets() if not str(a.package_name).startswith(('/Game/', '/Engine/', '/Script/'))}
options = unreal.AssetRegistryDependencyOptions(include_soft_package_references=True, include_hard_package_references=True, include_searchable_names=True, include_soft_management_references=True, include_hard_management_references=True)
reachable = set(roots)
pending = list(roots)
while pending:
    for dependency in registry.get_dependencies(pending.pop(), options):
        dependency = str(dependency)
        if dependency not in reachable:
            reachable.add(dependency)
            pending.append(dependency)
candidates = sorted(packages - reachable)
rows = []
for package in candidates:
    refs = [str(p) for p in registry.get_referencers(package, options)]
    base = root / 'Content' / package.removeprefix('/Game/')
    files = [p for p in base.parent.glob(base.name + '.*') if p.suffix.lower() in ('.uasset', '.uexp', '.ubulk', '.uptnl')]
    rows.append({'package': package, 'referencers': refs, 'files': [str(p.relative_to(root)) for p in files], 'bytes': sum(p.stat().st_size for p in files)})
report = {'package_count': len(packages), 'maps': sorted(maps), 'dynamic_roots': sorted(dynamic), 'protected_root_count': len(roots), 'reachable_game_count': len(packages & reachable), 'candidate_count': len(rows), 'candidate_bytes': sum(r['bytes'] for r in rows), 'candidates': rows, 'policy': 'Every map and authored thermal/route/vehicle/developer library retained. All registry reference types traversed. Review before quarantine; no deletion performed.'}
(out / 'asset_audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
unreal.log('ASSET_AUDIT_COMPLETE ' + str({k:v for k,v in report.items() if k not in ('candidates', 'maps', 'dynamic_roots')}))

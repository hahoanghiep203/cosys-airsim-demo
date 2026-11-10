"""Root-owned canonical settings and reversible unused-content quarantine."""
import hashlib
import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[2]
assert root.name == 'Cosys_Airsim'
backup = root / 'Saved/ProjectMaintenance/config_before_finalization'
backup.mkdir(parents=True, exist_ok=True)
def save(relative, text):
    file = root / relative
    old = backup / relative
    if file.exists() and not old.exists():
        old.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, old)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding='utf-8')

engine = (root / 'Config/DefaultEngine.ini').read_text()
engine = engine.replace('/Game/CityPark/Maps/Showcase_CoordinateCrop.Showcase_CoordinateCrop', '/Game/CityPark/Maps/Showcase.Showcase')
engine = engine.replace('GlobalDefaultGameMode=/Game/ThirdPersonBP/Blueprints/ThirdPersonGameMode.ThirdPersonGameMode_C', 'GlobalDefaultGameMode=/Script/AirSim.AirSimGameMode')
save('Config/DefaultEngine.ini', engine)
save('.gitignore', (root / '.gitignore').read_text()+'\n# Local capture runtime and reversible asset archive\n.venv/\nAssetArchive/\n__pycache__/\n*.pyc\n')
for name, scene in [('Open_Cosys_Airsim.cmd', 'original'), ('Open_OriginalMap_Balanced.cmd', 'original'), ('Open_Thermal_Scene.cmd', 'thermal'), ('Open_RouteCaptureDemo.cmd', 'route')]:
    save(name, '@echo off\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Scripts\\ScenePerformance\\launch_cosys.ps1" -Scene '+scene+' %*\n')
save('Scripts/Thermal/Open_Thermal_Scene.ps1', '& (Join-Path $PSScriptRoot "../ScenePerformance/launch_cosys.ps1") -Scene thermal\n')
for relative in ('Scripts/ScenePerformance/launch_original_map.ps1', 'Scripts/RouteCaptureDemo/launch_demo_editor.ps1'):
    file = root / relative
    save(relative, file.read_text().replace('AirSim_test.uproject','Cosys_Airsim.uproject'))
# Original-map launcher delegates to the single guarded entry point.
save('Scripts/ScenePerformance/launch_original_map.ps1', 'param([ValidateSet("baseline","balanced")][string]$Profile="balanced",[switch]$Offscreen)\n& (Join-Path $PSScriptRoot "launch_cosys.ps1") -Profile $Profile -Scene original -Offscreen:$Offscreen\n')
# Record exact installed distributions; this is a local CPython 3.12 environment.
import subprocess
freeze = subprocess.check_output([str(root / '.venv/Scripts/python.exe'), '-m', 'pip', 'freeze'], text=True)
save('Config/RouteCapture/requirements-win-py312.txt', freeze)

audit = json.loads((root / 'Saved/ProjectMaintenance/asset_audit.json').read_text())
candidate_set = {a['package'] for a in audit['candidates']}
archive = root / 'AssetArchive/unused_20261021'
assert not archive.exists(), 'Archive already exists: do not repeat cleanup'
files=[]
for row in audit['candidates']:
    assert row['package'].startswith('/Game/CityPark/')
    assert not set(row['referencers'])-candidate_set, row['package']
    for relative in row['files']:
        file=(root / relative).resolve()
        assert file.is_relative_to((root / 'Content/CityPark').resolve())
        assert file.is_file()
        files.append({'path': relative, 'bytes': file.stat().st_size, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
archive.mkdir(parents=True)
manifest={'archive':str(archive),'packages':sorted(candidate_set),'files':files,'bytes':sum(f['bytes'] for f in files),'policy':audit['policy']}
# Manifest exists before moving the first asset, allowing partial recovery.
save('Docs/ProjectMaintenance/asset_quarantine.json',json.dumps(manifest,indent=2))
for row in files:
    file=root / row['path']; destination=archive / row['path']
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.move(str(file),str(destination))
    assert hashlib.sha256(destination.read_bytes()).hexdigest()==row['sha256']
print(json.dumps({'quarantined_packages':len(candidate_set),'bytes_removed_from_content':manifest['bytes'],'backup':str(backup)}))

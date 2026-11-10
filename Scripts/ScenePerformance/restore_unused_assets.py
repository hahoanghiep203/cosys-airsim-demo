"""Restore quarantined assets with the editor closed; never overwrite a changed asset."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[2]
manifest=json.loads((root/'Docs/ProjectMaintenance/asset_quarantine.json').read_text())
archive=(root/'AssetArchive/unused_20261021').resolve()
content=(root/'Content').resolve()
if subprocess.check_output(['powershell.exe','-NoProfile','-Command','@(Get-Process UnrealEditor,UnrealEditor-Cmd -ErrorAction SilentlyContinue).Count'],text=True).strip()!='0':
    raise RuntimeError('Close Unreal before restoring assets.')
plan=[]
for row in manifest['files']:
    target=(root/row['path']).resolve(); source=(archive/row['path']).resolve()
    assert target.is_relative_to(content) and source.is_relative_to(archive)
    if target.exists():
        assert hashlib.sha256(target.read_bytes()).hexdigest()==row['sha256'],str(target)
        continue
    assert source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest()==row['sha256'],str(source)
    plan.append((source,target))
for source,target in plan:
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)
print('Restored',len(plan),'files. Archive retained.')

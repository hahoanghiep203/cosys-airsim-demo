"""One-time, backed-up canonical project consolidation; never copies existing maps."""
import datetime
import hashlib
import json
import shutil
from pathlib import Path

source = Path(__file__).resolve().parents[2]
target = source.parent / 'Cosys_Airsim'
assert target.resolve() == Path('D:/F1/UE prj/airsim_test/Cosys_Airsim').resolve()
stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
backup = target / 'Saved/ProjectMaintenance' / ('before_' + stamp)
backup.mkdir(parents=True)
manifest = []

def write(relative, data):
    destination = target / relative
    if destination.exists():
        if destination.read_bytes() == data: return
        saved = backup / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, saved)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    manifest.append(relative)

def tree(relative):
    for file in (source / relative).rglob('*'):
        if file.is_file() and not any(p in ('__pycache__', 'Intermediate', 'Binaries') for p in file.relative_to(source / relative).parts):
            write(str(file.relative_to(source)), file.read_bytes())

protected = target / 'Content/CityPark/Maps/Showcase_CoordinateCrop.umap'
protected_hash = hashlib.sha256(protected.read_bytes()).hexdigest()
shutil.copy2(protected, backup / protected.name)
for directory in ('Plugins/AirSimRouteCapture', 'Content/RouteCapture', 'Config/RouteCapture', 'Config/ScenePerformance', 'Scripts/RouteCaptureDemo', 'Scripts/ScenePerformance', 'Docs/RouteCapture', 'Docs/ScenePerformance'):
    tree(directory)
for name in ('RouteCaptureBridge.cpp', 'RouteCaptureBridge.h', 'SimHUD/SimHUD.cpp', 'ThermalWorldSubsystem.cpp'):
    relative = 'Plugins/AirSim/Source/' + name
    write(relative, (source / relative).read_bytes())

descriptor = json.loads((target / 'Cosys_Airsim.uproject').read_text())
descriptor['Modules'] = [{'Name': 'Cosys_Airsim', 'Type': 'Runtime', 'LoadingPhase': 'Default'}]
write('Cosys_Airsim.uproject', (json.dumps(descriptor, indent=2)+'\n').encode())
for suffix, kind in (('', 'Game'), ('Editor', 'Editor')):
    text = f'''using UnrealBuildTool;
public class Cosys_Airsim{suffix}Target : TargetRules {{
    public Cosys_Airsim{suffix}Target(TargetInfo Target) : base(Target) {{
        Type = TargetType.{kind};
        DefaultBuildSettings = BuildSettingsVersion.V6;
        IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_7;
        ExtraModuleNames.Add("Cosys_Airsim");
    }}
}}
'''
    write(f'Source/Cosys_Airsim{suffix}.Target.cs', text.encode())
write('Source/Cosys_Airsim/Cosys_Airsim.Build.cs', b'using UnrealBuildTool;\npublic class Cosys_Airsim : ModuleRules {\n public Cosys_Airsim(ReadOnlyTargetRules Target) : base(Target) {\n PCHUsage=PCHUsageMode.UseExplicitOrSharedPCHs;\n PublicDependencyModuleNames.AddRange(new string[] {"Core", "CoreUObject", "Engine"});\n }\n}\n')
write('Source/Cosys_Airsim/Cosys_Airsim.cpp', b'#include "Modules/ModuleManager.h"\nIMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, Cosys_Airsim, "Cosys_Airsim");\n')
assert hashlib.sha256(protected.read_bytes()).hexdigest() == protected_hash
(backup.parent / 'consolidation.json').write_text(json.dumps({'backup': str(backup), 'changed_files': manifest, 'protected_map_sha256': protected_hash}, indent=2))
print(json.dumps({'backup': str(backup), 'changed_files': len(manifest), 'map_preserved': True}))

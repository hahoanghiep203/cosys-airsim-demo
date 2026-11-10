param([ValidateRange(1,5)][int]$Scene=5,[switch]$Offscreen)
$ErrorActionPreference='Stop'
$diversityRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
if(Get-Process -Name 'llama-server*','prism*' -ErrorAction SilentlyContinue){throw 'Unload local inference before opening Unreal.'}
$existing=Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^UnrealEditor(-Cmd)?\.exe$' -and $_.CommandLine -match '(Cosys_Airsim|AirSim_test)\.uproject' -and (Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue)}
if($existing){throw 'An AirSim editor is already open. Close it yourself before opening another scene.'}
$configuration=Get-Content -LiteralPath (Join-Path $diversityRoot 'Config/SceneDiversity/scenes.json') -Raw | ConvertFrom-Json
$selection=$configuration.scenes[$Scene-1]
$commands='sg.ShadowQuality 1,sg.PostProcessQuality 1,sg.EffectsQuality 1,sg.ReflectionQuality 1,sg.GlobalIlluminationQuality 1,r.Streaming.PoolSize 6144,r.Streaming.LimitPoolSizeToVRAM 1,airsim.Rendering.PlanarReflectionBudget 1,airsim.Thermal.GpuPreview 1,airsim.Thermal.LiveHz 30,airsim.Camera.RgbPreviewHz 30,t.IdleWhenNotForeground 0,Slate.bAllowThrottling 0'
$startup=(Join-Path $PSScriptRoot 'startup.py').Replace('\','/')
$commands+=',py exec(open(r'''+$startup+''').read())'
$output=Join-Path $diversityRoot 'Saved/SceneDiversity'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$arguments=@('"'+(Join-Path $diversityRoot 'Cosys_Airsim.uproject')+'"',$selection.map,'-settings="'+(Join-Path $diversityRoot 'Config/EveningSample/settings.json')+'"','-ResX=1280','-ResY=720','-nosourcecontrol','-nosplash','-nosound','-ExecCmds="'+$commands+'"','-abslog="'+(Join-Path $output ($selection.id+'_editor.log'))+'"')
$window='Normal'
if($Offscreen){$arguments+=@('-RenderOffscreen','-unattended');$window='Hidden'}
$process=Start-Process -FilePath 'D:/WIP/UE editor/UE_5.7/Engine/Binaries/Win64/UnrealEditor.exe' -ArgumentList $arguments -WindowStyle $window -PassThru
$process.Id | Set-Content -LiteralPath (Join-Path $output 'editor_pid.txt')
Write-Output ('Thermal scene '+$Scene+' editor PID: '+$process.Id)

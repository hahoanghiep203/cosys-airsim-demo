param([switch]$Offscreen)
$ErrorActionPreference='Stop'
$sampleRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
if(Get-Process -Name 'llama-server*','prism*' -ErrorAction SilentlyContinue){throw 'Unload local inference before opening Unreal.'}
$sampleExisting=Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^UnrealEditor(-Cmd)?\.exe$' -and $_.CommandLine -match '(Cosys_Airsim|AirSim_test)\.uproject'}
if($sampleExisting){throw 'An AirSim editor is already open. Close it before opening the sample.'}
$sampleCommands='sg.ShadowQuality 1,sg.PostProcessQuality 1,sg.EffectsQuality 1,sg.ReflectionQuality 1,sg.GlobalIlluminationQuality 1,r.Streaming.PoolSize 6144,r.Streaming.LimitPoolSizeToVRAM 1,airsim.Rendering.PlanarReflectionBudget 1,airsim.Thermal.GpuPreview 1,airsim.Thermal.LiveHz 30,airsim.Camera.RgbPreviewHz 30,t.IdleWhenNotForeground 0,Slate.bAllowThrottling 0'
$sampleScript=(Join-Path $PSScriptRoot 'startup_sample.py').Replace('\','/')
$sampleCommands+=',py exec(open(r'''+$sampleScript+''').read())'
$sampleOutput=Join-Path $sampleRoot 'Saved/EveningSample'
New-Item -ItemType Directory -Path $sampleOutput -Force|Out-Null
$sampleArgs=@('"'+(Join-Path $sampleRoot 'Cosys_Airsim.uproject')+'"','/Game/CityPark/Maps/Showcase_EveningSample','-settings="'+(Join-Path $sampleRoot 'Config/EveningSample/settings.json')+'"','-ResX=1280','-ResY=720','-nosourcecontrol','-nosplash','-nosound','-ExecCmds="'+$sampleCommands+'"','-abslog="'+(Join-Path $sampleOutput 'editor.log')+'"')
$sampleWindow='Normal'
if($Offscreen){$sampleArgs+=@('-RenderOffscreen','-unattended');$sampleWindow='Hidden'}
$sampleProcess=Start-Process -FilePath 'D:/WIP/UE editor/UE_5.7/Engine/Binaries/Win64/UnrealEditor.exe' -ArgumentList $sampleArgs -WindowStyle $sampleWindow -PassThru
$sampleProcess.Id|Set-Content -LiteralPath (Join-Path $sampleOutput 'editor_pid.txt')
Write-Output ('Sample editor PID: '+$sampleProcess.Id)

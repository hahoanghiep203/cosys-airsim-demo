param([ValidateSet('baseline','balanced')][string]$Profile='balanced', [ValidateSet('original','notoptimized')][string]$Scene='original', [switch]$Offscreen)
$ErrorActionPreference='Stop'
$sceneRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
if (Get-Process -Name 'llama-server*','prism*' -ErrorAction SilentlyContinue) { throw 'Unload local inference before opening Unreal.' }
$sceneOpen=Get-CimInstance Win32_Process -Filter "Name='UnrealEditor.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains('airsim_test') }
if($sceneOpen){throw 'An AirSim editor is already open. Use that editor or close it before launching another.'}
$sceneMap=@{original='/Game/CityPark/Maps/Showcase';notoptimized='/Game/CityPark/Maps/Showcase_NotOptimized'}[$Scene]
$sceneSettings='Config/Thermal/settings_scene.json'
$sceneCommands='sg.ShadowQuality 1,sg.PostProcessQuality 1,sg.EffectsQuality 1,sg.ReflectionQuality 1,sg.GlobalIlluminationQuality 1,airsim.Rendering.PlanarReflectionBudget 1,airsim.Thermal.GpuPreview 1,airsim.Thermal.LiveHz 30,airsim.Camera.RgbPreviewHz 30,t.IdleWhenNotForeground 0,Slate.bAllowThrottling 0'
if($Profile -eq 'balanced'){
 $sceneBudget=Get-Content -LiteralPath (Join-Path $PSScriptRoot '../../Config/ScenePerformance/balanced.json') -Raw | ConvertFrom-Json
 foreach($sceneVariable in $sceneBudget.console_variables.PSObject.Properties){$sceneCommands+=','+$sceneVariable.Name+' '+$sceneVariable.Value}
}
$sceneScript=(Join-Path $PSScriptRoot 'startup.py').Replace('\','/')
$sceneCommands+=',py exec(open(r'''+$sceneScript+''').read()); scene_start('''+$Profile+''')'
$sceneOutput=Join-Path $sceneRoot 'Saved/ScenePerformance'
New-Item -ItemType Directory -Path $sceneOutput -Force | Out-Null
$sceneArguments=@('"'+(Join-Path $sceneRoot 'Cosys_Airsim.uproject')+'"',$sceneMap,'-settings="'+(Join-Path $sceneRoot $sceneSettings)+'"','-ResX=1280','-ResY=720','-nosourcecontrol','-nosplash','-nosound','-ExecCmds="'+$sceneCommands+'"','-abslog="'+(Join-Path $sceneOutput 'editor.log')+'"')
$sceneWindow='Normal'
if($Offscreen){$sceneArguments+=@('-RenderOffscreen','-unattended');$sceneWindow='Hidden'}
$sceneProcess=Start-Process -FilePath 'D:/WIP/UE editor/UE_5.7/Engine/Binaries/Win64/UnrealEditor.exe' -ArgumentList $sceneArguments -WindowStyle $sceneWindow -PassThru
$sceneProcess.Id | Set-Content -LiteralPath (Join-Path $sceneOutput 'editor_process_id.txt')
Write-Output ('Cosys editor PID: '+$sceneProcess.Id)

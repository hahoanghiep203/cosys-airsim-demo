$routeProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$routeOutput = Join-Path $routeProjectRoot 'Saved/RouteCaptureReview'
New-Item -ItemType Directory -Path $routeOutput -Force | Out-Null
$routeBridge = (Join-Path $PSScriptRoot 'editor_bridge.py').Replace('\','/')
$routeStartupMap = if (Test-Path -LiteralPath (Join-Path $routeProjectRoot 'Content/RouteCapture/Maps/RouteCaptureDemo.umap')) { '/Game/RouteCapture/Maps/RouteCaptureDemo' } else { '/Engine/Maps/Entry' }
$routeExec = '-ExecCmds="py exec(open(r''' + $routeBridge + ''').read()),t.IdleWhenNotForeground 0,Slate.bAllowThrottling 0,airsim.Thermal.LiveHz 0,airsim.Camera.RgbPreviewHz 0"'
$routeArguments = @('"' + (Join-Path $routeProjectRoot 'Cosys_Airsim.uproject') + '"', $routeStartupMap, '-settings="' + (Join-Path $routeProjectRoot 'Config/RouteCapture/settings_demo.json') + '"', '-RenderOffscreen', '-unattended', '-nosourcecontrol', '-nosplash', '-nosound', $routeExec, '-abslog="' + (Join-Path $routeOutput 'editor.log') + '"')
$routeProcess = Start-Process -FilePath 'D:/WIP/UE editor/UE_5.7/Engine/Binaries/Win64/UnrealEditor.exe' -ArgumentList $routeArguments -WindowStyle Hidden -PassThru
$routeProcess.Id | Set-Content -LiteralPath (Join-Path $routeOutput 'editor_process_id.txt')
Write-Output ('Isolated route-test editor PID: ' + $routeProcess.Id)

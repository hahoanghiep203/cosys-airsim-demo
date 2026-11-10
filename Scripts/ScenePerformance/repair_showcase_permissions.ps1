# Grants only the current project user permission to replace this one map.
$repairIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$repairPrincipal = [System.Security.Principal.WindowsPrincipal]::new($repairIdentity)
if (-not $repairPrincipal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $repairArguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $PSCommandPath + '"'))
    $repairProcess = Start-Process -FilePath 'powershell.exe' -ArgumentList $repairArguments -Verb RunAs -WindowStyle Hidden -Wait -PassThru
    exit $repairProcess.ExitCode
}
$ErrorActionPreference = 'Stop'
$repairRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$repairMap = (Resolve-Path -LiteralPath (Join-Path $repairRoot 'Content/CityPark/Maps/Showcase.umap')).Path
$repairOutput = Join-Path $repairRoot 'Saved/ScenePerformance'
New-Item -ItemType Directory -Path $repairOutput -Force | Out-Null
try {
    $repairAcl = Get-Acl -LiteralPath $repairMap
    $repairBackup = Join-Path $repairOutput 'showcase_acl_before_repair.txt'
    if (-not (Test-Path -LiteralPath $repairBackup)) { $repairAcl.Sddl | Set-Content -LiteralPath $repairBackup }
    $repairUser = 'DESKTOP-ASRBKR8\Admin'
    $repairRule = [System.Security.AccessControl.FileSystemAccessRule]::new($repairUser,[System.Security.AccessControl.FileSystemRights]::Modify,[System.Security.AccessControl.AccessControlType]::Allow)
    $repairAcl.AddAccessRule($repairRule)
    Set-Acl -LiteralPath $repairMap -AclObject $repairAcl
    $repairVerified = (Get-Acl -LiteralPath $repairMap).Access | Where-Object { $_.IdentityReference -eq $repairUser -and $_.AccessControlType -eq 'Allow' -and ($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::Modify) -eq [System.Security.AccessControl.FileSystemRights]::Modify }
    if (-not $repairVerified) { throw 'Modify permission was not confirmed.' }
    @{success=$true;map=$repairMap;account=$repairUser;permission='Modify';note='Map bytes unchanged. Retry saving in the existing Unreal editor.'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $repairOutput 'permission_repair_result.json')
} catch {
    @{success=$false;error=$_.Exception.Message;map=$repairMap} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $repairOutput 'permission_repair_result.json')
    exit 1
}

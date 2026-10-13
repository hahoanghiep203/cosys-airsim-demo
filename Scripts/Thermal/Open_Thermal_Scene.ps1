$thermalRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
& 'D:/WIP/UE editor/UE_5.7/Engine/Binaries/Win64/UnrealEditor.exe' (Join-Path $thermalRoot 'Cosys_Airsim.uproject') '/Game/CityPark/Maps/Showcase_CoordinateCrop' ('-settings=' + (Join-Path $thermalRoot 'Config/Thermal/settings_scene.json'))

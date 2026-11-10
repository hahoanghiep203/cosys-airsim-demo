using UnrealBuildTool;
public class AirSimRouteCaptureEditor : ModuleRules
{
    public AirSimRouteCaptureEditor(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PrivateDependencyModuleNames.AddRange(new[] { "Core", "CoreUObject", "Engine", "AirSimRouteCapture", "UnrealEd", "Slate", "SlateCore", "ToolMenus", "PropertyEditor", "LevelEditor" });
    }
}

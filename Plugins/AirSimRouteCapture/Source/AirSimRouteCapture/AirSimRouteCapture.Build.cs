using UnrealBuildTool;
public class AirSimRouteCapture : ModuleRules
{
    public AirSimRouteCapture(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new[] { "Core", "CoreUObject", "Engine", "Json" });
        PrivateDependencyModuleNames.AddRange(new[] { "AirSim", "Projects" });
    }
}

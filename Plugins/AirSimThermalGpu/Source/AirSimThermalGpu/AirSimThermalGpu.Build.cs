using UnrealBuildTool;

public class AirSimThermalGpu : ModuleRules
{
    public AirSimThermalGpu(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new[] { "Core", "CoreUObject", "Engine", "RenderCore", "RHI" });
        PrivateDependencyModuleNames.AddRange(new[] { "Renderer", "Projects" });
        PrivateIncludePaths.Add(System.IO.Path.Combine(EngineDirectory, "Source/Runtime/Renderer/Internal"));
    }
}

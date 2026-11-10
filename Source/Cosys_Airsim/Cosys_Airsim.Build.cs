using UnrealBuildTool;
public class Cosys_Airsim : ModuleRules {
 public Cosys_Airsim(ReadOnlyTargetRules Target) : base(Target) {
 PCHUsage=PCHUsageMode.UseExplicitOrSharedPCHs;
 PublicDependencyModuleNames.AddRange(new string[] {"Core", "CoreUObject", "Engine"});
 }
}

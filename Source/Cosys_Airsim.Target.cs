using UnrealBuildTool;
public class Cosys_AirsimTarget : TargetRules {
    public Cosys_AirsimTarget(TargetInfo Target) : base(Target) {
        Type = TargetType.Game;
        DefaultBuildSettings = BuildSettingsVersion.V6;
        IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_7;
        ExtraModuleNames.Add("Cosys_Airsim");
    }
}

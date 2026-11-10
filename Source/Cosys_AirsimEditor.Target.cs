using UnrealBuildTool;
public class Cosys_AirsimEditorTarget : TargetRules {
    public Cosys_AirsimEditorTarget(TargetInfo Target) : base(Target) {
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.V6;
        IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_7;
        ExtraModuleNames.Add("Cosys_Airsim");
    }
}

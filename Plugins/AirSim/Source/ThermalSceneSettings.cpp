#include "ThermalSceneSettings.h"
#include "ThermalWorldSubsystem.h"
#include "Components/SceneComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "EngineUtils.h"
#include "TimerManager.h"

namespace {
bool ContainsAny(const FString& Name, std::initializer_list<const TCHAR*> Words)
{
    for (const TCHAR* Word : Words) if (Name.Contains(Word)) return true;
    return false;
}
void SetBaseline(TArray<FName>& Tags, const FString& Category, float Celsius, float Emissivity)
{
    Tags.RemoveAll([](FName Tag) {
        const FString Text = Tag.ToString();
        return Text.StartsWith(TEXT("ThermalBaselineK=")) || Text.StartsWith(TEXT("ThermalBaselineEmissivity=")) || Text.StartsWith(TEXT("ThermalCategory="));
    });
    Tags.Add(FName(*FString::Printf(TEXT("ThermalBaselineK=%.2f"), FMath::Clamp(Celsius + 273.15f, 1.f, 1999.f))));
    Tags.Add(FName(*FString::Printf(TEXT("ThermalBaselineEmissivity=%.3f"), Emissivity)));
    Tags.Add(FName(*(TEXT("ThermalCategory=") + Category)));
}
}
AThermalSceneSettings::AThermalSceneSettings()
{
    RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("SceneSettingsRoot"));
    PrimaryActorTick.bCanEverTick = false;
}
void AThermalSceneSettings::BeginPlay()
{
    Super::BeginPlay();
    ApplySceneTemperatures();
    // AirSim creates its camera/vehicle meshes after level actors begin play.
    // Catch those once startup has finished, preserving explicit overrides.
    GetWorld()->GetTimerManager().SetTimerForNextTick(this, &AThermalSceneSettings::ApplySceneTemperatures);
}
void AThermalSceneSettings::ApplySceneTemperatures()
{
    UWorld* World = GetWorld();
    if (!World) return;
    AssignedMeshComponents = AssignedMeshInstances = 0;
    for (TObjectIterator<UStaticMeshComponent> It; It; ++It) {
        auto* C = *It;
        if (C->GetWorld() != World || !C->IsRegistered() || !C->GetStaticMesh()) continue;
        const FString Name = C->GetStaticMesh()->GetName().ToLower();
        // CityPark's water planes are decorative transparent puddle/reflection
        // layers. They do not represent independent thermal receiving surfaces.
        if (Name.StartsWith(TEXT("sm_waterplane"))) C->ComponentTags.AddUnique(TEXT("ThermalIgnore"));
        FString Category = TEXT("default"); float Temperature = DefaultTemperatureCelsius, Emissivity = .9f;
        if (ContainsAny(Name, {TEXT("sky")})) { Category=TEXT("sky"); Temperature=-3.15f; Emissivity=1; }
        else if (ContainsAny(Name, {TEXT("grass"),TEXT("lawn")})) { Category=TEXT("grass"); Temperature=GrassTemperatureCelsius; Emissivity=.97f; }
        else if (ContainsAny(Name, {TEXT("bush"),TEXT("plant"),TEXT("flower")})) { Category=TEXT("bush"); Temperature=BushTemperatureCelsius; Emissivity=.97f; }
        else if (ContainsAny(Name, {TEXT("tree"),TEXT("elm"),TEXT("maple"),TEXT("amur"),TEXT("willow"),TEXT("pine"),TEXT("oak")})) { Category=TEXT("tree"); Temperature=TreeTemperatureCelsius; Emissivity=.97f; }
        else if (ContainsAny(Name, {TEXT("asphalt"),TEXT("road"),TEXT("street")})) { Category=TEXT("road"); Temperature=RoadTemperatureCelsius; Emissivity=.95f; }
        else if (ContainsAny(Name, {TEXT("water")})) { Category=TEXT("water"); Temperature=WaterTemperatureCelsius; Emissivity=.98f; }
        else if (ContainsAny(Name, {TEXT("car"),TEXT("hatchback"),TEXT("sedan"),TEXT("suv"),TEXT("truck"),TEXT("vehicle")})) { Category=TEXT("vehicle"); Temperature=VehicleTemperatureCelsius; Emissivity=.93f; }
        else if (ContainsAny(Name, {TEXT("path"),TEXT("square"),TEXT("concrete"),TEXT("sidewalk"),TEXT("bridge"),TEXT("curb"),TEXT("floor")})) { Category=TEXT("concrete"); Temperature=ConcreteTemperatureCelsius; Emissivity=.95f; }
        else if (ContainsAny(Name, {TEXT("rock"),TEXT("soil"),TEXT("dirt"),TEXT("ground")})) { Category=TEXT("ground"); Temperature=GroundTemperatureCelsius; Emissivity=.93f; }
        else if (ContainsAny(Name, {TEXT("lamp"),TEXT("metal"),TEXT("fence"),TEXT("railing"),TEXT("sign"),TEXT("trash"),TEXT("bin"),TEXT("hydrant"),TEXT("pole")})) { Category=TEXT("metal"); Temperature=MetalTemperatureCelsius; Emissivity=.75f; }
        else if (ContainsAny(Name, {TEXT("bench"),TEXT("wood"),TEXT("table")})) { Category=TEXT("wood"); Temperature=WoodTemperatureCelsius; Emissivity=.90f; }
        else if (ContainsAny(Name, {TEXT("wall"),TEXT("roof"),TEXT("building"),TEXT("house")})) { Category=TEXT("building"); Temperature=BuildingTemperatureCelsius; Emissivity=.92f; }
#if WITH_EDITOR
        if (World->WorldType == EWorldType::Editor) { C->Modify(); C->GetOwner()->Modify(); }
#endif
        SetBaseline(C->ComponentTags, Category, Temperature, Emissivity);
        ++AssignedMeshComponents;
        AssignedMeshInstances += Cast<UInstancedStaticMeshComponent>(C) ? Cast<UInstancedStaticMeshComponent>(C)->GetInstanceCount() : 1;
    }
    for (TActorIterator<AActor> It(World); It; ++It) {
        if (!It->GetClass()->GetName().StartsWith(TEXT("Landscape"))) continue;
#if WITH_EDITOR
        if (World->WorldType == EWorldType::Editor) It->Modify();
#endif
        SetBaseline(It->Tags, TEXT("grass"), GrassTemperatureCelsius, .97f);
        It->Tags.AddUnique(TEXT("ThermalBoundsFallback"));
    }
    if (auto* System = World->GetSubsystem<UThermalWorldSubsystem>()) System->ResetThermalState();
}

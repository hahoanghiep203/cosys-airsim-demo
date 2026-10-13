#include "ThermalMath.h"
#include "ThermalSource.h"
#include "ThermalWorldSubsystem.h"
#include "ThermalObjectSettings.h"
#include "ThermalSceneSettings.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/SplineMeshComponent.h"
#include "Misc/AutomationTest.h"
#include "Engine/World.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "SyntheticCameraProcessor.h"
#include "common/AirSimSettings.hpp"

#if WITH_DEV_AUTOMATION_TESTS
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalDecorativeTest, "AirSim.Thermal.DecorativeSurfacesIgnoreHeat",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalDecorativeTest::RunTest(const FString&)
{
    auto* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (!TestNotNull(TEXT("Decorative fixture mesh"), Cube)) return false;
    auto* World = UWorld::CreateWorld(EWorldType::Game, false);
    auto* Actor = World->SpawnActor<AActor>();
    auto* Mesh = NewObject<UStaticMeshComponent>(Actor);
    Actor->SetRootComponent(Mesh); Actor->AddInstanceComponent(Mesh);
    Mesh->SetStaticMesh(Cube); Mesh->RegisterComponent();
    Mesh->ComponentTags.Add(TEXT("ThermalIgnore"));
    auto* Source = World->SpawnActor<AThermalSource>();
    Source->ParentReceiver = Actor; Source->TemperatureKelvin = 350;
    Source->Prewarm(1);
    TestEqual(TEXT("Decoration allocates no receiving samples even near an emitter"), Source->GetThermalSampleCount(), 0);
    Mesh->ComponentTags.Reset(); Source->Prewarm(1);
    TestTrue(TEXT("Real receiving surface still heats"), Source->GetThermalSampleCount() > 0);
    Mesh->ComponentTags.Add(TEXT("ThermalIgnore")); Source->Prewarm(1);
    TestEqual(TEXT("Marking an existing surface decorative removes its samples"), Source->GetThermalSampleCount(), 0);
    World->DestroyWorld(false);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalGpuHashTest, "AirSim.Thermal.GpuDenseSpatialGrid",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalGpuHashTest::RunTest(const FString&)
{
    const FThermalGpuGrid Grid{FIntVector4(-10,-5,-2,7), FIntVector4(21,11,5,0)};
    TestEqual(TEXT("Negative coordinates address the first cell"), ThermalGpuData::DenseCellIndex(Grid,FIntVector(-10,-5,-2)),7);
    TestEqual(TEXT("X cells are adjacent in memory"), ThermalGpuData::DenseCellIndex(Grid,FIntVector(-9,-5,-2)),8);
    TestEqual(TEXT("Out-of-grid cells do not alias another receiver"), ThermalGpuData::DenseCellIndex(Grid,FIntVector(-11,-5,-2)),INDEX_NONE);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalGpuFrameTest, "AirSim.Thermal.GpuFrameUsesPersistentHeat",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalGpuFrameTest::RunTest(const FString&)
{
    auto* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (!TestNotNull(TEXT("GPU packing fixture mesh"), Cube)) return false;
    auto* World = UWorld::CreateWorld(EWorldType::Game, false);
    auto* Actor = World->SpawnActor<AActor>();
    auto* Mesh = NewObject<UStaticMeshComponent>(Actor);
    Actor->SetRootComponent(Mesh); Actor->AddInstanceComponent(Mesh);
    Mesh->SetStaticMesh(Cube); Mesh->RegisterComponent();
    auto* Source = World->SpawnActor<AThermalSource>();
    Source->ParentReceiver = Actor;
    Source->TemperatureKelvin = 350;
    Source->SetActorLocation(FVector(51,0,0));
    Source->Prewarm(1);
    auto* System = World->GetSubsystem<UThermalWorldSubsystem>();
    const auto First = System->MakeGpuFrame();
    const auto Unchanged = System->MakeGpuFrame();
    TestTrue(TEXT("Stationary topology stays shared, not copied per camera frame"), First.Topology == Unchanged.Topology);
    TestTrue(TEXT("Temperature data stays shared until heat advances"), First.Temperatures == Unchanged.Temperatures);
    TestEqual(TEXT("Every GPU sample has a temperature value"), First.Topology->Samples.Num(), First.Temperatures->Values.Num());
    const float OldTemperature = First.Temperatures->Values[0].X;
    Source->Prewarm(2);
    const auto Heated = System->MakeGpuFrame();
    TestTrue(TEXT("Advancing heat preserves immutable GPU geometry"), First.Topology == Heated.Topology);
    TestTrue(TEXT("A new heat step publishes new temperature values"), First.Temperatures != Heated.Temperatures);
    TestEqual(TEXT("The prior frame's values remain immutable"), First.Temperatures->Values[0].X, OldTemperature);
    bool Hot = false; for (const auto& V : Heated.Temperatures->Values) Hot |= V.X > 296;
    TestTrue(TEXT("GPU data contains the persistent heated surface, not emitter volumes"), Hot);
    World->DestroyWorld(false);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalAnnotatedReceiverTest, "AirSim.Thermal.AnnotationRestrictsSurfaceLookup",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalAnnotatedReceiverTest::RunTest(const FString&)
{
    FThermalFrameSnapshot Frame;
    Frame.HasSegmentationReceiverMap = true;
    auto& Receiver = Frame.Receivers.AddDefaulted_GetRef();
    Receiver.Transform = FTransform::Identity;
    Receiver.WorldBounds = FBox(FVector(90,-10,-10),FVector(110,10,10));
    FThermalSurfaceSample Surface;
    Surface.LocalPosition = FVector(100,0,0); Surface.TemperatureKelvin = 333.15f;
    Receiver.Samples.FindOrAdd(FIntVector(12,0,0)).Add(Surface);
    Frame.ReceiversByColor.FindOrAdd(0x010203).Add(0);
    std::vector<float> Temperature, Emissivity;
    Frame.ResolvePixels({1},1,1,Temperature,Emissivity,{}, {1,2,3});
    TestTrue(TEXT("Matching annotation samples the heated receiver"), FMath::IsNearlyEqual(Temperature[0],333.15f));
    Frame.ResolvePixels({1},1,1,Temperature,Emissivity,{}, {4,5,6});
    TestTrue(TEXT("Another object's pixel keeps its baseline despite overlapping receiver bounds"), !FMath::IsFinite(Temperature[0]));
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalSceneDefaultsTest, "AirSim.Thermal.SceneDefaultsPreserveOverrides",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalSceneDefaultsTest::RunTest(const FString&)
{
    UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (!TestNotNull(TEXT("Scene test cube is available"), Cube)) return false;
    UWorld* World = UWorld::CreateWorld(EWorldType::Game, false);
    AActor* Actor = World->SpawnActor<AActor>();
    auto* Mesh = NewObject<UStaticMeshComponent>(Actor);
    Actor->SetRootComponent(Mesh); Actor->AddInstanceComponent(Mesh);
    Mesh->SetStaticMesh(Cube); Mesh->RegisterComponent();
    Actor->Tags.Add(FName(TEXT("ThermalTempK=313.15")));
    auto* Settings = World->SpawnActor<AThermalSceneSettings>();
    Settings->DefaultTemperatureCelsius = 26;
    Settings->ApplySceneTemperatures();
    float Assigned = 0;
    TestTrue(TEXT("One scene controller assigns baseline tags without adding heat actors"),
        ThermalObjectSettings::ReadTag(Mesh->ComponentTags, TEXT("ThermalBaselineK"), Assigned) && FMath::IsNearlyEqual(Assigned, 299.15f));
    TestTrue(TEXT("Per-object manual settings survive applying scene defaults"), FMath::IsNearlyEqual(ThermalObjectSettings::Resolve(Mesh).TemperatureKelvin, 313.15f));
    TestEqual(TEXT("Scene reports its assigned mesh count"), Settings->AssignedMeshComponents, 1);
    World->DestroyWorld(false);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalSplineReceiverTest, "AirSim.Thermal.DeformedSplineReceivers",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalSplineReceiverTest::RunTest(const FString&)
{
    UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (!TestNotNull(TEXT("Spline test mesh is available"), Cube)) return false;
    UWorld* World = UWorld::CreateWorld(EWorldType::Game, false);
    AActor* Actor = World->SpawnActor<AActor>();
    auto* Mesh = NewObject<USplineMeshComponent>(Actor);
    Actor->SetRootComponent(Mesh); Actor->AddInstanceComponent(Mesh);
    Mesh->SetStaticMesh(Cube);
    Mesh->SetStartAndEnd(FVector(500, 0, 0), FVector(100, 0, 0), FVector(600, 0, 0), FVector(100, 0, 0));
    Mesh->RegisterComponent();
    auto* Source = World->SpawnActor<AThermalSource>();
    Source->SetActorLocation(FVector(400, 0, 0));
    Source->TemperatureKelvin = 600; Source->RadiusCm=100; Source->RangeCm=300;
    Source->HeatParentSurface=false; Source->Occlusion=false;
    auto* System = World->GetSubsystem<UThermalWorldSubsystem>();
    System->RegisterSource(Source); System->Prewarm(20);
    TestTrue(TEXT("Heat reaches rendered spline placement"), System->GetSurfaceTemperature(FVector(500, 0, 0)) > 295);
    TestEqual(TEXT("Undeformed source mesh does not create a ghost heat surface"), System->GetSurfaceTemperature(FVector(-50, 0, 0)), -1.f);
    World->DestroyWorld(false);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalObjectSettingsTest, "AirSim.Thermal.WholeObjectSettings",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalObjectSettingsTest::RunTest(const FString&)
{
    UWorld* World = UWorld::CreateWorld(EWorldType::Game, false);
    AActor* Actor = World->SpawnActor<AActor>();
    auto* Mesh = NewObject<UStaticMeshComponent>(Actor);
    Actor->SetRootComponent(Mesh);
    Actor->AddInstanceComponent(Mesh);
    Actor->Tags = { FName(TEXT("ThermalBaselineK=291.15")), FName(TEXT("ThermalBaselineEmissivity=0.97")) };
    Mesh->ComponentTags = { FName(TEXT("ThermalBaselineK=305.15")) };
    auto Values = ThermalObjectSettings::Resolve(Mesh);
    TestTrue(TEXT("Scene component baseline is independent of any heat source"), FMath::IsNearlyEqual(Values.TemperatureKelvin, 305.15f));
    TestTrue(TEXT("Actor emissivity applies to the whole object"), FMath::IsNearlyEqual(Values.Emissivity, .97f));
    Actor->Tags.Add(FName(TEXT("ThermalTempK=313.15")));
    Values = ThermalObjectSettings::Resolve(Mesh);
    TestTrue(TEXT("Manual actor temperature overrides automatic scene baseline"), FMath::IsNearlyEqual(Values.TemperatureKelvin, 313.15f));
    Mesh->ComponentTags.Add(FName(TEXT("ThermalTempK=323.15")));
    Values = ThermalObjectSettings::Resolve(Mesh);
    TestTrue(TEXT("Manual component temperature can override its actor"), FMath::IsNearlyEqual(Values.TemperatureKelvin, 323.15f));
    auto* Response = NewObject<UThermalReceiverComponent>(Actor);
    Actor->AddInstanceComponent(Response);
    Response->BaselineTemperatureKelvin = 303.15;
    Response->Emissivity = .88;
    Values = ThermalObjectSettings::Resolve(Mesh);
    TestTrue(TEXT("Editable receiver component has highest temperature priority"), FMath::IsNearlyEqual(Values.TemperatureKelvin, 303.15f));
    TestTrue(TEXT("Editable receiver emissivity takes priority"), FMath::IsNearlyEqual(Values.Emissivity, .88f));
    float Parsed = 298;
    TestFalse(TEXT("Invalid tag leaves a valid value unchanged"), ThermalObjectSettings::ReadTag({FName(TEXT("ThermalTempK=bad"))}, TEXT("ThermalTempK"), Parsed));
    TestEqual(TEXT("Invalid tag did not overwrite temperature"), Parsed, 298.f);
    World->DestroyWorld(false);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalBaselinePixelsTest, "AirSim.Thermal.NoSourceBaselineAndTerrain",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalBaselinePixelsTest::RunTest(const FString&)
{
    FThermalFrameSnapshot Frame;
    std::vector<float> Temperatures, Emissivity;
    Frame.ResolvePixels({1.f, 1.f}, 2, 1, Temperatures, Emissivity);
    TestEqual(TEXT("No-source frame still enables fixed radiometric profile rendering"), int32(Temperatures.size()), 2);
    TestTrue(TEXT("Unsampled object pixels use their whole-object profile"), !FMath::IsFinite(Temperatures[0]));
    FThermalUniformSurface Terrain;
    Terrain.WorldBounds = FBox(FVector(90, -100, -100), FVector(110, 100, 100));
    Terrain.TemperatureKelvin = 291.15;
    Terrain.Emissivity = .97;
    Frame.UniformUnannotatedSurfaces.Add(Terrain);
    Frame.ResolvePixels({1.f, 1.f}, 2, 1, Temperatures, Emissivity, {}, {0,0,0, 20,30,40});
    TestTrue(TEXT("Unannotated terrain receives its own baseline"), FMath::IsNearlyEqual(Temperatures[0], 291.15f));
    TestTrue(TEXT("Annotated road/foliage inside terrain bounds keeps its own profile"), !FMath::IsFinite(Temperatures[1]));
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalInstancedReceiverTest, "AirSim.Thermal.InstancedReceivers",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalInstancedReceiverTest::RunTest(const FString&)
{
    UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (!TestNotNull(TEXT("Instance test mesh is available"), Cube)) return false;
    UWorld* World = UWorld::CreateWorld(EWorldType::Game, false);
    AActor* Actor = World->SpawnActor<AActor>();
    auto* Mesh = NewObject<UInstancedStaticMeshComponent>(Actor);
    Actor->SetRootComponent(Mesh); Actor->AddInstanceComponent(Mesh);
    Mesh->SetStaticMesh(Cube);
    Mesh->AddInstance(FTransform(FVector(200, 0, 0)));
    Mesh->AddInstance(FTransform(FVector(1200, 0, 0)));
    Mesh->ComponentTags.Add(FName(TEXT("ThermalBaselineK=293.15")));
    Mesh->RegisterComponent();
    auto* Source = World->SpawnActor<AThermalSource>();
    Source->HeatParentSurface = false; Source->Occlusion = false;
    Source->TemperatureKelvin = 600; Source->RadiusCm = 100; Source->RangeCm = 300;
    auto* System = World->GetSubsystem<UThermalWorldSubsystem>();
    System->RegisterSource(Source); System->Prewarm(20);
    TestTrue(TEXT("Nearby instance heats at its actual world placement"), System->GetSurfaceTemperature(FVector(150, 0, 0)) > 295);
    TestEqual(TEXT("No invisible base mesh is sampled at component origin"), System->GetSurfaceTemperature(FVector(-50, 0, 0)), -1.f);
    TestEqual(TEXT("Distant instances do not allocate local heat surfaces"), System->GetSurfaceTemperature(FVector(1150, 0, 0)), -1.f);
    World->DestroyWorld(false);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalEnergyTest, "AirSim.Thermal.EnergyAndPersistence",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalEnergyTest::RunTest(const FString&)
{
    const double Ambient = 295, Capacity = 1500, Cooling = 12;
    double Single = Ambient, Overlap = Ambient;
    for (int I = 0; I < 600; ++I) {
        Single = ThermalMath::Integrate(Single, Ambient, 1000, Capacity, Cooling, .1);
        Overlap = ThermalMath::Integrate(Overlap, Ambient, 2000, Capacity, Cooling, .1);
    }
    TestTrue(TEXT("Two energy emitters raise temperature more than one"), Overlap > Single + 10);
    TestTrue(TEXT("Energy addition doubles excess, not absolute Kelvin"), FMath::IsNearlyEqual(Overlap - Ambient, 2 * (Single - Ambient), .001));
    const double Heated = Single;
    for (int I = 0; I < 100; ++I) Single = ThermalMath::Integrate(Single, Ambient, 0, Capacity, Cooling, .1);
    TestTrue(TEXT("Disabling a source retains heat and gradually cools"), Single < Heated && Single > Ambient + 1);
    const double LargeStep = ThermalMath::Integrate(Heated, Ambient, 0, Capacity, Cooling, 100000);
    TestTrue(TEXT("Cooling does not overshoot ambient"), LargeStep >= Ambient && LargeStep < Heated);
    TestTrue(TEXT("Higher heat capacity heats more slowly"), ThermalMath::Integrate(Ambient, Ambient, 1000, 3000, Cooling, 10) < ThermalMath::Integrate(Ambient, Ambient, 1000, 500, Cooling, 10));
    TestTrue(TEXT("Cold sources exchange negative net radiation"), ThermalMath::Radiation(280, 320) < 0);
    double LowCapacity = Ambient;
    for (int I = 0; I < 100; ++I) {
        const double Next = ThermalMath::IntegrateTransfers(LowCapacity, Ambient, 80 * 450, 80, 0, 0, 1, 12, .1);
        TestTrue(TEXT("Low-capacity contact heating never overshoots or oscillates"), Next >= LowCapacity && Next <= 450);
        LowCapacity = Next;
    }
    const double Mixed = ThermalMath::IntegrateTransfers(295, 295, 80 * 450 + 80 * 500, 160, 0, 0, 1, 12, .1);
    TestTrue(TEXT("Overlapping low-capacity sources remain within thermal bounds"), Mixed > 295 && Mixed < 500);
    const double RadiationCoefficient = ThermalMath::StefanBoltzmann * .9;
    const double Radiated = ThermalMath::IntegrateTransfers(295, 295, 0, 0,
        RadiationCoefficient * FMath::Pow(600.0, 4.0), RadiationCoefficient, 1, 12, 10);
    TestTrue(TEXT("Implicit nonlinear radiation never overshoots emitter temperature"), Radiated > 295 && Radiated < 600);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalProjectionTest, "AirSim.Thermal.DepthProjectionAndSnapshot",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalProjectionTest::RunTest(const FString&)
{
    const FTransform Camera(FRotator(0, 90, 0), FVector(100, 200, 300));
    const FVector Center = ThermalMath::PlanarPixelWorld(Camera, 1, 2, 1, 5, 3, 2);
    TestTrue(TEXT("Uses UE world origin and rotated forward, with m-to-cm depth"), Center.Equals(FVector(100, 400, 300), .001));
    const FVector Right = ThermalMath::PlanarPixelWorld(FTransform::Identity, 1, 4, 1, 5, 3, 2);
    TestTrue(TEXT("Planar depth is forward depth, not radial range"), FMath::IsNearlyEqual(Right.X, 200.0, .001) && Right.Y > 0);
    const FVector Portrait = ThermalMath::PlanarPixelWorld(FTransform::Identity, 1, 1, 0, 3, 5, 2);
    TestTrue(TEXT("Portrait capture preserves horizontal FOV like UE5.7 SceneCaptureRendering BuildProjectionMatrix"), FMath::IsNearlyEqual(Portrait.Z, 800.0 / 3, .001));
    FThermalFrameSnapshot Frame;
    auto& R = Frame.Receivers.AddDefaulted_GetRef();
    R.Transform = FTransform(FRotator::ZeroRotator, FVector(100, 0, 0));
    R.WorldBounds = FBox(FVector(90, -10, -10), FVector(110, 10, 10));
    FThermalSurfaceSample Sample;
    Sample.TemperatureKelvin = 370;
    R.Samples.Add(FIntVector::ZeroValue, TArray<FThermalSurfaceSample>{ Sample });
    float T = 0, E = 0;
    TestTrue(TEXT("Local samples follow receiver transform"), Frame.Sample(FVector(100, 0, 0), T, E) && T == 370);
    TestFalse(TEXT("Hot sample cannot paint a distant depth surface"), Frame.Sample(FVector(100, 0, 40), T, E));
    Sample.LocalPosition.Z = 1;
    Sample.LocalNormal = FVector::UpVector;
    Sample.TemperatureKelvin = 400;
    Sample.Emissivity = .95f;
    auto& ThinBucket = R.Samples.FindChecked(FIntVector::ZeroValue);
    ThinBucket.Reset(); ThinBucket.Add(Sample);
    Sample.LocalPosition.Z = 2;
    Sample.LocalNormal = -FVector::UpVector;
    Sample.TemperatureKelvin = 295;
    Sample.Emissivity = .35f;
    Sample.MaterialIndex = 1;
    ThinBucket.Add(Sample);
    TestTrue(TEXT("Opposite thin faces in one voxel keep independent temperatures/materials"),
        Frame.Sample(FVector(100, 0, 1.5), T, E, -FVector::UpVector) && T == 295 && FMath::IsNearlyEqual(E, .35f));
    TestTrue(TEXT("Hot outward face remains distinct from occluded inward face"),
        Frame.Sample(FVector(100, 0, 1), T, E, FVector::UpVector) && T == 400 && FMath::IsNearlyEqual(E, .95f));
    R.Samples.Reset();
    Sample.LocalPosition = FVector::ZeroVector;
    Sample.LocalNormal = FVector::UpVector;
    Sample.MaterialIndex = 0;
    Sample.TemperatureKelvin = 300;
    R.Samples.Add(FIntVector::ZeroValue, TArray<FThermalSurfaceSample>{ Sample });
    Sample.LocalPosition.X = 8;
    Sample.TemperatureKelvin = 400;
    R.Samples.Add(FIntVector(1, 0, 0), TArray<FThermalSurfaceSample>{ Sample });
    TestTrue(TEXT("Same surface interpolates temperatures between neighbouring voxels"),
        Frame.Sample(FVector(104, 0, 0), T, E, FVector::UpVector) && FMath::IsNearlyEqual(T, 350.f, .01f));
    float Left = 0, RightTemp = 0;
    Frame.Sample(FVector(103.9, 0, 0), Left, E, FVector::UpVector);
    Frame.Sample(FVector(104.1, 0, 0), RightTemp, E, FVector::UpVector);
    TestTrue(TEXT("Crossing a voxel midpoint has no temperature step"), RightTemp > Left && RightTemp - Left < 15);
    R.Samples.FindChecked(FIntVector(1, 0, 0))[0].MaterialIndex = 1;
    TestTrue(TEXT("Interpolation never blends neighbouring materials"),
        Frame.Sample(FVector(103.9, 0, 0), T, E, FVector::UpVector) && T == 300);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalShapeTest, "AirSim.Thermal.ShapeAndFalloff",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalShapeTest::RunTest(const FString&)
{
    TestTrue(TEXT("Distance inverse-square falloff"), ThermalMath::DistanceWeight(20, 10, 300) > ThermalMath::DistanceWeight(80, 10, 300));
    TestEqual(TEXT("Finite range cuts off emission"), ThermalMath::DistanceWeight(300, 10, 300), 0.0);
    TestEqual(TEXT("Spot outside cone is dark"), ThermalMath::ConeWeight(0, 20, 40), 0.0);
    TestTrue(TEXT("Spot core exceeds penumbra"), ThermalMath::ConeWeight(1, 20, 40) > ThermalMath::ConeWeight(FMath::Cos(FMath::DegreesToRadians(30.0)), 20, 40));
    UWorld* World = UWorld::CreateWorld(EWorldType::Game, false);
    AThermalSource* Source = World->SpawnActor<AThermalSource>();
    if (!TestNotNull(TEXT("Native source spawns without visual assets"), Source)) { World->DestroyWorld(false); return false; }
    Source->RangeCm = 300;
    TestTrue(TEXT("Point faces receiver"), Source->GetRadiationWeight(FVector(50, 0, 0), FVector(-1, 0, 0)) > 0);
    TestEqual(TEXT("Backface does not absorb radiation"), Source->GetRadiationWeight(FVector(50, 0, 0), FVector(1, 0, 0)), 0.0);
    Source->SourceType = EThermalSourceType::Rect;
    Source->RectWidthCm = 100;
    TestTrue(TEXT("Rect extends emission over its face"), Source->GetEmitterPoint(FVector(50, 40, 0)).Equals(FVector(0, 40, 0)));
    Source->RectHeightCm = 2000;
    TestTrue(TEXT("Tall rectangle discovery includes the full emitter height"), Source->GetDiscoveryRadius() > 1000);
    Source->SourceType = EThermalSourceType::Capsule;
    Source->CapsuleLengthCm = 100;
    TestTrue(TEXT("Capsule radiates along segment"), Source->GetEmitterPoint(FVector(10, 0, 40)).Equals(FVector(0, 0, 40)));
    Source->SourceType = EThermalSourceType::Directional;
    Source->RadiusCm = 50;
    TestEqual(TEXT("Directional beam rejects points behind source"), Source->GetRadiationWeight(FVector(-10, 0, 0), FVector(-1, 0, 0)), 0.0);
    TestEqual(TEXT("Directional beam rejects points outside footprint"), Source->GetRadiationWeight(FVector(10, 80, 0), FVector(-1, 0, 0)), 0.0);
    TestTrue(TEXT("Directional beam has parallel rays"), FMath::IsNearlyEqual(Source->GetRadiationWeight(FVector(20, 0, 0), FVector(-1, 0, 0)), Source->GetRadiationWeight(FVector(200, 0, 0), FVector(-1, 0, 0))));
    Source->RadiusCm = 2000;
    TestTrue(TEXT("Wide directional beam discovery includes full footprint"), Source->GetDiscoveryRadius() > 2000);
    World->DestroyWorld(false);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalOcclusionTest, "AirSim.Thermal.WorldOcclusionAndOffCameraHeating",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalOcclusionTest::RunTest(const FString&)
{
    UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
    if (!TestNotNull(TEXT("Test mesh is available"), Cube)) return false;
    UWorld* World = UWorld::CreateWorld(EWorldType::Game, false);
    const auto MakeReceiver = [World, Cube](FVector Position, FVector Scale) {
        AActor* Actor = World->SpawnActor<AActor>();
        auto* Mesh = NewObject<UStaticMeshComponent>(Actor);
        Actor->SetRootComponent(Mesh);
        Actor->AddInstanceComponent(Mesh);
        Mesh->SetStaticMesh(Cube);
        Mesh->SetCollisionProfileName(TEXT("BlockAll"));
        Mesh->RegisterComponent();
        Mesh->SetWorldLocation(Position);
        Mesh->SetWorldScale3D(Scale);
        return Mesh;
    };
    auto* Receiver = MakeReceiver(FVector(200, 0, 0), FVector::OneVector);
    auto* Blocker = MakeReceiver(FVector(75, 0, 0), FVector(.3, 2, 2));
    AThermalSource* Source = World->SpawnActor<AThermalSource>();
    Source->HeatParentSurface = false;
    Source->TemperatureKelvin = 600;
    Source->RadiusCm = 100;
    Source->RangeCm = 300;
    auto* System = World->GetSubsystem<UThermalWorldSubsystem>();
    if (!TestNotNull(TEXT("World thermal subsystem exists"), System)) { World->DestroyWorld(false); return false; }
    System->RegisterSource(Source);
    System->Prewarm(20);
    const FVector Probe(150, 0, 0);
    const float Blocked = System->GetSurfaceTemperature(Probe);
    TestTrue(TEXT("Receiver surface exists independent of camera capture"), Blocked > 0);
    Blocker->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    System->ResetThermalState();
    System->Prewarm(20);
    const float Open = System->GetSurfaceTemperature(Probe);
    TestTrue(TEXT("Occluder blocks energy reaching receiver"), Open > Blocked + 2);
    Source->SetSourceEnabled(false);
    System->Prewarm(10);
    const float Cooling = System->GetSurfaceTemperature(Probe);
    TestTrue(TEXT("Off-camera warm surface persists while source is off"), Cooling < Open && Cooling > 295.5);
    // Geometry stays unchanged; attached heat is another transfer term.
    Source->SetSourceEnabled(true);
    Source->HeatParentSurface = true;
    Source->ParentReceiver = Receiver->GetOwner();
    Source->SetActorLocation(Probe);
    Source->ParentContactRadiusCm = 30;
    Source->ParentConductance = 80;
    System->ResetThermalState();
    System->Prewarm(10);
    TestTrue(TEXT("Local parent surface receives contact energy"), System->GetSurfaceTemperature(Probe) > 315);
    Source->ParentMaterialIndices = { 7 };
    Source->RangeCm = 1;
    System->ResetThermalState();
    System->Prewarm(10);
    TestTrue(TEXT("Material allowlist rejects contact energy on actual parent mesh"),
        FMath::IsNearlyEqual(System->GetSurfaceTemperature(Probe), 295.f, .01f));
    Source->SetActorLocation(FVector::ZeroVector);
    Source->RangeCm = 300;
    System->ResetThermalState();
    System->Prewarm(20);
    TestTrue(TEXT("Parent contact material mask does not disable physical radiation"), System->GetSurfaceTemperature(Probe) > 297);
    World->DestroyWorld(false);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalCylinderContactTest, "AirSim.Thermal.AnnularCylinderParentContact",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalCylinderContactTest::RunTest(const FString&)
{
    UWorld* World = UWorld::CreateWorld(EWorldType::Game, false);
    AThermalSource* Source = World->SpawnActor<AThermalSource>();
    if (!TestNotNull(TEXT("Cylinder source spawns"), Source)) { World->DestroyWorld(false); return false; }
    Source->ParentContactRadiusCm = 45;
    TestEqual(TEXT("Default contact retains full weight at point origin"), Source->GetContactWeight(FVector::ZeroVector), 1.0);
    TestEqual(TEXT("Default contact retains smooth radial falloff"), Source->GetContactWeight(FVector(22.5, 0, 0)), .5);
    TestEqual(TEXT("Default contact retains its spatial cutoff"), Source->GetContactWeight(FVector(46, 0, 0)), 0.0);
    Source->ParentContactRegion = EThermalContactRegion::FiniteCylinder;
    Source->ParentContactInnerRadiusCm = 20;
    Source->ParentContactOuterRadiusCm = 40;
    Source->ParentContactHalfLengthCm = 12;
    for (int Arc = 0; Arc < 12; ++Arc) {
        const double Angle = Arc * PI / 6;
        const FVector Point(5, 30 * FMath::Cos(Angle), 30 * FMath::Sin(Angle));
        TestEqual(TEXT("Every opposite tire arc receives the same flat coverage"), Source->GetContactWeight(Point), 1.0);
    }
    TestEqual(TEXT("Cylinder interior rim/bore receives no contact heat"), Source->GetContactWeight(FVector(0, 10, 0)), 0.0);
    TestEqual(TEXT("Cylinder excludes body beyond outer radius"), Source->GetContactWeight(FVector(0, 41, 0)), 0.0);
    TestEqual(TEXT("Cylinder excludes body beyond positive axle length"), Source->GetContactWeight(FVector(13, 30, 0)), 0.0);
    TestEqual(TEXT("Cylinder excludes body beyond negative axle length"), Source->GetContactWeight(FVector(-13, 30, 0)), 0.0);
    TestEqual(TEXT("Cylinder includes exact radial and axial boundaries"), Source->GetContactWeight(FVector(12, 20, 0)), 1.0);
    TestTrue(TEXT("Empty material allowlist preserves all slots"), Source->IsParentMaterialAllowed(0) && Source->IsParentMaterialAllowed(5));
    Source->ParentMaterialIndices = { 1, 3 };
    TestTrue(TEXT("Allowlist includes configured parent material slots"), Source->IsParentMaterialAllowed(1) && Source->IsParentMaterialAllowed(3));
    TestFalse(TEXT("Allowlist rejects unselected parent material slots"), Source->IsParentMaterialAllowed(0));
    Source->SetActorTransform(FTransform(FRotator(0, 90, 0), FVector(100, 200, 300)));
    const FVector WorldArc = Source->GetActorTransform().TransformPosition(FVector(5, 30, 0));
    TestEqual(TEXT("Rotated wheel axle and attached position use source local coordinates"), Source->GetContactWeight(WorldArc), 1.0);
    Source->ParentContactInnerRadiusCm = 50;
    TestEqual(TEXT("Invalid reversed radial region applies no contact heat"), Source->GetContactWeight(WorldArc), 0.0);
    World->DestroyWorld(false);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FThermalDisplayTest, "AirSim.Thermal.FixedRadiometricDisplay",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FThermalDisplayTest::RunTest(const FString&)
{
    auto& Settings = msr::airlib::AirSimSettings::singleton().synthetic_camera.thermal_ir;
    const auto Saved = Settings;
    Settings.display_temp_min = 280;
    Settings.display_temp_max = 380;
    Settings.depth_attenuation = 0;
    const int Width = 20;
    std::vector<uint8_t> Segmentation(Width * 3, 0), Baseline, Heated, Cooling, WiderWindow, LowEmissivity;
    std::vector<float> Temperatures(Width, 298), Emissivity(Width, .92f);
    for (int I = 0; I < 5; ++I) Temperatures[I] = 295;
    auto Compose = [&](std::vector<uint8_t>& Image) {
        SyntheticCameraProcessor::instance().composeThermalIR(Segmentation, {}, {}, {}, Width, 1,
            Image, Temperatures, Emissivity);
    };
    Compose(Baseline);
    TestTrue(TEXT("298K baseline stays within display midtones instead of white silhouette"), Baseline[10 * 3] > 30 && Baseline[10 * 3] < 120);
    Temperatures[19] = 350;
    Compose(Heated);
    TestEqual(TEXT("An unrelated hotspot cannot change unchanged surface brightness"), Heated[10 * 3], Baseline[10 * 3]);
    TestTrue(TEXT("Actual heated pixels brighten within the fixed window"), Heated[19 * 3] > Baseline[19 * 3] + 40);
    Temperatures[19] = 325;
    Compose(Cooling);
    TestTrue(TEXT("Cooling has comparable brightness between baseline and hot frame"), Cooling[19 * 3] > Baseline[19 * 3] && Cooling[19 * 3] < Heated[19 * 3]);
    Settings.display_temp_max = 480;
    Compose(WiderWindow);
    TestTrue(TEXT("Live display setting changes immediately update normalization"), WiderWindow[10 * 3] < Baseline[10 * 3]);
    Settings.display_temp_max = 380;
    Temperatures[19] = 350;
    Emissivity[19] = .01f;
    Compose(LowEmissivity);
    TestTrue(TEXT("Low emissivity correctly reduces hot surface radiance"), LowEmissivity[19 * 3] < Heated[19 * 3]);
    Settings = Saved;
    return true;
}
#endif

#include "RouteCaptureBridge.h"
#include "SimMode/SimModeBase.h"
#include "PawnSimApi.h"
#include "PIPCamera.h"
#include "EngineUtils.h"
#include "Engine/World.h"
#include "GameFramework/WorldSettings.h"
#include "Engine/TextureRenderTarget2D.h"
#include "vehicles/multirotor/api/MultirotorApiBase.hpp"

namespace {
ASimModeBase* RouteSim(UWorld* World)
{
    for (TActorIterator<ASimModeBase> It(World); It; ++It) return *It;
    return nullptr;
}
}

bool FRouteCaptureBridge::Resolve(UWorld* World, const FString& Vehicle, const FString& Camera, FRouteCaptureVehicleContext& Out, FString& Error)
{
    auto* Sim = World ? RouteSim(World) : nullptr;
    if (!Sim || !Sim->getApiProvider()) { Error = TEXT("AirSim is not ready in the active Play world."); return false; }
    auto* Api = Sim->getVehicleSimApi(TCHAR_TO_UTF8(*Vehicle));
    if (!Api) { Error = TEXT("Selected AirSim vehicle does not exist."); return false; }
    // Resolve through the selected API's actual name, including default-vehicle
    // selection, rather than interpreting the mission's requested vehicle name.
    const auto ActualVehicleName=Api->getVehicleName();
    // AirSim's getter otherwise falls back to "SimpleFlight" for a missing name.
    // Firmware gating must use this vehicle's own entry, or fail closed.
    if (msr::airlib::AirSimSettings::singleton().vehicles.count(ActualVehicleName)==0) { Error=TEXT("Selected AirSim vehicle has no matching active settings entry."); return false; }
    const auto* VehicleSettings=msr::airlib::AirSimSettings::singleton().getVehicleSetting(ActualVehicleName);
    if (!VehicleSettings || VehicleSettings->vehicle_type.empty()) { Error=TEXT("Selected AirSim vehicle type is unavailable."); return false; }
    Out.VehicleType=UTF8_TO_TCHAR(VehicleSettings->vehicle_type.c_str());
    if (VehicleSettings->vehicle_type != msr::airlib::AirSimSettings::kVehicleTypeSimpleFlight) { Error=TEXT("Route capture currently requires a SimpleFlight multirotor."); return false; }
    auto* Flight=static_cast<msr::airlib::MultirotorApiBase*>(Sim->getApiProvider()->getVehicleApi(TCHAR_TO_UTF8(*Vehicle)));
    if (!Flight) { Error=TEXT("Selected multirotor flight API is unavailable."); return false; }
    Out.Landed=Flight->getMultirotorState().landed_state==msr::airlib::LandedState::Landed;
    auto* Cam = Api->getCamera(TCHAR_TO_UTF8(*Camera));
    if (!Cam) { Error = TEXT("Selected camera does not exist."); return false; }
    auto* Capture = Cam->getCaptureComponent(APIPCamera::ImageType::Scene, false);
    auto* Target = Cam->getRenderTarget(APIPCamera::ImageType::Scene, false);
    if (!Capture || !Target) { Error = TEXT("Selected RGB camera is not configured."); return false; }
    auto* Depth=Cam->getCaptureComponent(APIPCamera::ImageType::DepthPlanar,false);
    auto* DepthTarget=Cam->getRenderTarget(APIPCamera::ImageType::DepthPlanar,false);
    auto* SegTarget=Cam->getRenderTarget(APIPCamera::ImageType::Segmentation,false);
    auto* NormalTarget=Cam->getRenderTarget(APIPCamera::ImageType::SurfaceNormals,false);
    if (!Depth || !DepthTarget || !SegTarget || !NormalTarget || DepthTarget->SizeX!=Target->SizeX || DepthTarget->SizeY!=Target->SizeY || SegTarget->SizeX!=Target->SizeX || SegTarget->SizeY!=Target->SizeY || NormalTarget->SizeX!=Target->SizeX || NormalTarget->SizeY!=Target->SizeY || !FMath::IsNearlyEqual(Depth->FOVAngle,Capture->FOVAngle,.01f)) { Error=TEXT("RGB and thermal auxiliary buffers must have matching resolution and FOV."); return false; }
    Out.Origin = Api->getNedTransform().getLocalOffset();
    Out.WorldOrigin = World->OriginLocation;
    Out.WorldToMeters = Api->getNedTransform().fromNed(1.0f);
    if (!FMath::IsNearlyEqual(Out.WorldToMeters,double(World->GetWorldSettings()->WorldToMeters),.001)) { Error=TEXT("WorldToMeters changed after the selected AirSim vehicle spawned; restart Play to resolve coordinates."); return false; }
    Out.SimulationSeconds = World->GetTimeSeconds();
    Out.Paused = Sim->isPaused();
    Out.Pawn = Api->getPawn();
    Out.BodyPosition = Api->getPawn()->GetActorLocation();
    Out.Width = Target->SizeX; Out.Height = Target->SizeY;
    Out.Fov = Capture->FOVAngle;
    Out.Projection = Capture->ProjectionType == ECameraProjectionMode::Perspective ? TEXT("perspective") : TEXT("orthographic");
    const auto& Settings = msr::airlib::AirSimSettings::singleton();
    Out.SimMode = UTF8_TO_TCHAR(Settings.simmode_name.c_str());
    Out.ThermalMin = Settings.synthetic_camera.thermal_ir.display_temp_min;
    Out.ThermalMax = Settings.synthetic_camera.thermal_ir.display_temp_max;
    return true;
}

bool FRouteCaptureBridge::ToLocalNed(UWorld* World, const FString& Vehicle, const FVector& Position, FVector& Out, FString& Error)
{
    auto* Sim = World ? RouteSim(World) : nullptr;
    auto* Api = Sim && Sim->getApiProvider() ? Sim->getVehicleSimApi(TCHAR_TO_UTF8(*Vehicle)) : nullptr;
    if (!Api) { Error = TEXT("Selected AirSim vehicle does not exist."); return false; }
    const auto P = Api->getNedTransform().toLocalNed(Position);
    Out = FVector(P.x(), P.y(), P.z()); return true;
}

void FRouteCaptureBridge::HideMarkersFromDroneCameras(UWorld* World)
{
    TArray<AActor*> Markers;
    for (TActorIterator<AActor> It(World); It; ++It) if (It->ActorHasTag(TEXT("RouteCaptureMarker"))) Markers.Add(*It);
    for (TActorIterator<APIPCamera> It(World); It; ++It) {
        TArray<USceneCaptureComponent2D*> Captures;
        It->GetComponents(Captures);
        for (auto* Capture : Captures) for (auto* Marker : Markers) Capture->HiddenActors.AddUnique(Marker);
    }
}

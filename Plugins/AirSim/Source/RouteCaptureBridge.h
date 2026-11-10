#pragma once
#include "CoreMinimal.h"
class APawn;

/** Narrow exported boundary. All access to unexported PawnSimApi stays in AirSim. */
struct AIRSIM_API FRouteCaptureVehicleContext
{
    FVector Origin = FVector::ZeroVector;
    FIntVector WorldOrigin = FIntVector::ZeroValue;
    FVector BodyPosition = FVector::ZeroVector;
    double WorldToMeters = 100;
    double SimulationSeconds = 0;
    bool Paused = false;
    bool Landed = true;
    int32 Width = 0, Height = 0;
    double Fov = 0, ThermalMin = 280, ThermalMax = 380;
    FString Projection, SimMode, VehicleType;
    TWeakObjectPtr<APawn> Pawn;
};

class AIRSIM_API FRouteCaptureBridge
{
public:
    static bool Resolve(UWorld* World, const FString& Vehicle, const FString& Camera, FRouteCaptureVehicleContext& Out, FString& Error);
    static bool ToLocalNed(UWorld* World, const FString& Vehicle, const FVector& WorldPosition, FVector& Out, FString& Error);
    static void HideMarkersFromDroneCameras(UWorld* World);
};

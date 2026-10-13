#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include <vector>
#include "ThermalGpuData.h"
#include "ThermalWorldSubsystem.generated.h"

class AThermalSource;
class UStaticMeshComponent;
struct FThermalSurfaceSample
{
    FVector LocalPosition = FVector::ZeroVector;
    FVector LocalNormal = FVector::UpVector;
    float TemperatureKelvin = 295;
    float Emissivity = .9f;
    float Capacity = 1500;
    float Cooling = 12;
    int32 MaterialIndex = 0;
};
struct FThermalReceiverState
{
    struct FTransfer
    {
        TWeakObjectPtr<AThermalSource> Source;
        double ContactConductance = 0;
        double RadiationViewFactor = 0;
    };
    TWeakObjectPtr<UStaticMeshComponent> Component;
    int32 InstanceIndex = INDEX_NONE;
    TMap<FIntVector, TArray<FThermalSurfaceSample>> Samples;
    TMap<FIntVector, TArray<TArray<FTransfer>>> Transfers;
    TMap<FIntVector, TArray<TArray<FTransfer>>> PendingTransfers;
    float SpacingCm = 8;
    float BaselineKelvin = 295;
};
struct FThermalSnapshotReceiver
{
    FTransform Transform;
    FBox WorldBounds;
    float SpacingCm = 8;
    TMap<FIntVector, TArray<FThermalSurfaceSample>> Samples;
};
struct FThermalUniformSurface
{
    FBox WorldBounds;
    float TemperatureKelvin = 295;
    float Emissivity = .9f;
};
/** Value-only snapshot: never contains UObject pointers and can be queried by RPC
 * or rendering workers after the frame's game-thread snapshot is complete. */
struct FThermalFrameSnapshot
{
    FTransform CameraTransform;
    double TanHalfHorizontalFov = 1;
    bool Perspective = true;
    TArray<FThermalSnapshotReceiver> Receivers;
    TArray<FThermalUniformSurface> UniformUnannotatedSurfaces;
    bool HasSegmentationReceiverMap = false;
    TMap<uint32, TArray<int32>> ReceiversByColor;
    bool Sample(const FVector& WorldPoint, float& Temperature, float& Emissivity,
                const FVector& WorldNormal = FVector::ZeroVector,
                const TArray<int32>* CandidateReceivers = nullptr) const;
    void ResolvePixels(const std::vector<float>& DepthMeters, int32 Width, int32 Height,
                       std::vector<float>& Temperature, std::vector<float>& Emissivity,
                       const std::vector<uint8_t>& NormalsRgb = {},
                       const std::vector<uint8_t>& SegmentationRgb = {}) const;
};

UCLASS()
class AIRSIM_API UThermalWorldSubsystem : public UTickableWorldSubsystem
{
    GENERATED_BODY()
public:
    virtual void Tick(float DeltaTime) override;
    virtual bool IsTickable() const override;
    virtual TStatId GetStatId() const override;
    virtual bool DoesSupportWorldType(EWorldType::Type Type) const override;
    void RegisterSource(AThermalSource* Source);
    void UnregisterSource(AThermalSource* Source);
    void ResetThermalState();
    void Prewarm(float Seconds);
    float GetSurfaceTemperature(const FVector& WorldPoint, const FVector& WorldNormal = FVector::ZeroVector) const;
    int32 GetSampleCount() const;
    FThermalFrameSnapshot MakeSnapshot() const;
    FThermalGpuFrame MakeGpuFrame();
private:
    void DiscoverReceivers(bool ImmediateTransfers = false);
    void AddReceiver(UStaticMeshComponent* Component, int32 InstanceIndex = INDEX_NONE);
    void RefreshTransfers(double BudgetSeconds = 0);
    void Advance(float Seconds);
    bool IsOccluded(const AThermalSource* Source, const UStaticMeshComponent* Receiver,
                    const FVector& Emitter, const FVector& Point, const FVector& Normal) const;
    TArray<TWeakObjectPtr<AThermalSource>> Sources;
    TArray<FThermalReceiverState> Receivers;
    float DiscoveryTimer = 0;
    float AccumulatedTime = 0;
    bool TransferRefreshPending = false;
    int32 TransferReceiverIndex = 0;
    int32 TransferBucketIndex = 0;
    TArray<FIntVector> TransferBucketKeys;
    uint64 GpuTopologyRevision = 1;
    uint64 GpuTemperatureRevision = 1;
    TSharedPtr<FThermalGpuTopology, ESPMode::ThreadSafe> GpuTopology;
    TSharedPtr<FThermalGpuTemperatures, ESPMode::ThreadSafe> GpuTemperatures;
    // Reuse immutable mesh topology. Temperature uploads follow simulation
    // updates (10 Hz) rather than the camera preview's 30 Hz.
    TArray<TArray<FIntVector>> GpuReceiverBucketOrder;
    TArray<TWeakObjectPtr<AActor>> GpuUniformActors;
    double GpuUniformRefreshTime = 0;
};

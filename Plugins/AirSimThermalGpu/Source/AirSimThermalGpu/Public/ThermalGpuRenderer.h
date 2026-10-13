#pragma once

#include "CoreMinimal.h"
#include "ThermalGpuData.h"

class FTextureRenderTargetResource;
struct FThermalGpuRenderState;

/** A GPU-resident camera preview; explicit RPC images read back a fresh GPU
 * frame. Immutable surface geometry is uploaded once, temperatures at simulation
 * cadence, and scene inputs/output never pass through CPU image buffers. */
class AIRSIMTHERMALGPU_API FThermalGpuRenderer
{
public:
    FThermalGpuRenderer();
    static bool IsSupported();
    bool Render(FThermalGpuFrame&& Frame,
        TSharedPtr<const TArray<FThermalGpuProfile>, ESPMode::ThreadSafe> Profiles, uint64 ProfileRevision,
        TSharedPtr<const TArray<float>, ESPMode::ThreadSafe> Radiance,
        const FTransform& Camera, float FovDegrees, FIntPoint Size, float DisplayMin, float DisplayMax, float DepthAttenuation,
        FTextureRenderTargetResource* Segmentation, FTextureRenderTargetResource* Depth,
        FTextureRenderTargetResource* Normals, FTextureRenderTargetResource* Output, bool PackedInputs = false);
    FString GetStats() const;
private:
    TSharedRef<FThermalGpuRenderState, ESPMode::ThreadSafe> State;
    uint64 ProfileTopologyRevision = 0;
    uint64 CachedProfileRevision = 0;
    TSharedPtr<TArray<FThermalGpuProfile>, ESPMode::ThreadSafe> ObjectTable;
    TSharedPtr<TArray<uint32>, ESPMode::ThreadSafe> CandidateTable;
};

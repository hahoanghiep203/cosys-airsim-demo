#pragma once
#include "CoreMinimal.h"

class FTextureRenderTargetResource;
class ISceneViewExtension;
struct FThermalGpuInputState;

/** Extract opaque/masked surface identity, depth and normals from one camera
 * render. Original material opacity and spline deformation remain intact. */
class AIRSIMTHERMALGPU_API FThermalGpuInputs
{
public:
    FThermalGpuInputs();
    ~FThermalGpuInputs();
    void Configure(FTextureRenderTargetResource* Camera, FTextureRenderTargetResource* Geometry,
        FTextureRenderTargetResource* Identity);
    uint64 GetCaptureCount() const;
private:
    TSharedRef<FThermalGpuInputState, ESPMode::ThreadSafe> State;
    TSharedPtr<ISceneViewExtension, ESPMode::ThreadSafe> Extension;
};

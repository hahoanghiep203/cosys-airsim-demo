#include "Modules/ModuleManager.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/Paths.h"
#include "ShaderCore.h"

// Global shader types must register before shader initialization. AirSim's
// UObject/camera module retains its original later loading phase.
class FAirSimThermalGpuModule : public IModuleInterface
{
public:
    virtual void StartupModule() override
    {
        if (const auto Plugin = IPluginManager::Get().FindPlugin(TEXT("AirSimThermalGpu")))
            AddShaderSourceDirectoryMapping(TEXT("/Plugin/AirSimThermalGpu"), FPaths::Combine(Plugin->GetBaseDir(), TEXT("Shaders")));
    }
};
IMPLEMENT_MODULE(FAirSimThermalGpuModule, AirSimThermalGpu)

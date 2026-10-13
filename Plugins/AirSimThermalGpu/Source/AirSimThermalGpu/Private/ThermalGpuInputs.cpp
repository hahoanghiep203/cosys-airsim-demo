#include "ThermalGpuInputs.h"
#include "SceneViewExtension.h"
#include "GlobalShader.h"
#include "ShaderParameterStruct.h"
#include "RenderGraphUtils.h"
#include "SceneTexturesConfig.h"
#include "PostProcess/PostProcessInputs.h"
#include "TextureResource.h"
#include <atomic>

class FThermalInputsCS : public FGlobalShader
{
public:
    DECLARE_GLOBAL_SHADER(FThermalInputsCS);
    SHADER_USE_PARAMETER_STRUCT(FThermalInputsCS, FGlobalShader);
    BEGIN_SHADER_PARAMETER_STRUCT(FParameters, )
        SHADER_PARAMETER(FIntPoint, ImageSize)
        SHADER_PARAMETER(FIntPoint, ViewMin)
        SHADER_PARAMETER_STRUCT_REF(FViewUniformShaderParameters, View)
        SHADER_PARAMETER_RDG_UNIFORM_BUFFER(FSceneTextureUniformParameters, SceneTextures)
        SHADER_PARAMETER_RDG_TEXTURE_UAV(RWTexture2D<float4>, GeometryOutput)
        SHADER_PARAMETER_RDG_TEXTURE_UAV(RWTexture2D<float4>, IdentityOutput)
    END_SHADER_PARAMETER_STRUCT()
    static bool ShouldCompilePermutation(const FGlobalShaderPermutationParameters& P)
    { return IsFeatureLevelSupported(P.Platform, ERHIFeatureLevel::SM5); }
};
IMPLEMENT_GLOBAL_SHADER(FThermalInputsCS, "/Plugin/AirSimThermalGpu/Private/ThermalInputs.usf", "ThermalInputsCS", SF_Compute);

struct FThermalGpuInputState
{
    // These pointers are updated and consumed only on the render thread.
    FTextureRenderTargetResource* Camera = nullptr;
    FTextureRenderTargetResource* Geometry = nullptr;
    FTextureRenderTargetResource* Identity = nullptr;
    std::atomic<uint64> Captures{0};
};

class FThermalInputExtension : public FSceneViewExtensionBase
{
public:
    FThermalInputExtension(const FAutoRegister& Register, TSharedRef<FThermalGpuInputState, ESPMode::ThreadSafe> InState)
        : FSceneViewExtensionBase(Register), State(InState) {}
    void SetupViewFamily(FSceneViewFamily&) override {}
    void SetupView(FSceneViewFamily&, FSceneView&) override {}
    void BeginRenderViewFamily(FSceneViewFamily&) override {}
    void PrePostProcessPass_RenderThread(FRDGBuilder& Graph, const FSceneView& View,
        const FPostProcessingInputs& Inputs) override
    {
        if (!State->Camera || View.Family->RenderTarget != State->Camera || !View.bIsSceneCapture ||
            !State->Geometry || !State->Identity || !Inputs.SceneTextures) return;
        const FTextureRHIRef Geometry = State->Geometry->GetRenderTargetTexture();
        const FTextureRHIRef Identity = State->Identity->GetRenderTargetTexture();
        if (!Geometry || !Identity) return;
        auto G = Graph.RegisterExternalTexture(CreateRenderTarget(Geometry, TEXT("Thermal.Geometry")));
        auto I = Graph.RegisterExternalTexture(CreateRenderTarget(Identity, TEXT("Thermal.Identity")));
        auto* P = Graph.AllocParameters<FThermalInputsCS::FParameters>();
        P->ImageSize = State->Geometry->GetSizeXY();
        P->ViewMin = View.UnscaledViewRect.Min;
        P->View = View.ViewUniformBuffer;
        P->SceneTextures = Inputs.SceneTextures;
        P->GeometryOutput = Graph.CreateUAV(G);
        P->IdentityOutput = Graph.CreateUAV(I);
        TShaderMapRef<FThermalInputsCS> Shader(GetGlobalShaderMap(View.GetFeatureLevel()));
        FComputeShaderUtils::AddPass(Graph, RDG_EVENT_NAME("AirSim Thermal camera inputs"), Shader, P,
            FComputeShaderUtils::GetGroupCount(P->ImageSize, FIntPoint(8, 8)));
        Graph.SetTextureAccessFinal(G, ERHIAccess::SRVMask);
        Graph.SetTextureAccessFinal(I, ERHIAccess::SRVMask);
        ++State->Captures;
    }
private:
    TSharedRef<FThermalGpuInputState, ESPMode::ThreadSafe> State;
};

FThermalGpuInputs::FThermalGpuInputs() : State(MakeShared<FThermalGpuInputState, ESPMode::ThreadSafe>())
{ Extension = FSceneViewExtensions::NewExtension<FThermalInputExtension>(State); }
FThermalGpuInputs::~FThermalGpuInputs() { Configure(nullptr, nullptr, nullptr); }
uint64 FThermalGpuInputs::GetCaptureCount() const { return State->Captures.load(); }
void FThermalGpuInputs::Configure(FTextureRenderTargetResource* Camera, FTextureRenderTargetResource* Geometry,
    FTextureRenderTargetResource* Identity)
{
    ENQUEUE_RENDER_COMMAND(ConfigureThermalInputs)([State = State, Camera, Geometry, Identity](FRHICommandListImmediate&) {
        State->Camera = Camera; State->Geometry = Geometry; State->Identity = Identity;
    });
}

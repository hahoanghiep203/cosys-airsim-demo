#include "ThermalGpuRenderer.h"
#include "GlobalShader.h"
#include "ShaderParameterStruct.h"
#include "RenderGraphBuilder.h"
#include "RenderGraphUtils.h"
#include "RenderTargetPool.h"
#include "TextureResource.h"
#include "DataDrivenShaderPlatformInfo.h"
#include <atomic>

class FThermalResolveCS : public FGlobalShader
{
public:
    DECLARE_GLOBAL_SHADER(FThermalResolveCS);
    SHADER_USE_PARAMETER_STRUCT(FThermalResolveCS, FGlobalShader);
    BEGIN_SHADER_PARAMETER_STRUCT(FParameters, )
        SHADER_PARAMETER(FIntPoint, ImageSize)
        SHADER_PARAMETER(uint32, ProfileMask)
        SHADER_PARAMETER(uint32, UniformCount)
        SHADER_PARAMETER(uint32, InputSrgbMask)
        SHADER_PARAMETER(FVector4f, CameraOrigin)
        SHADER_PARAMETER(FVector4f, CameraForward)
        SHADER_PARAMETER(FVector4f, CameraRight)
        SHADER_PARAMETER(FVector4f, CameraUp)
        SHADER_PARAMETER(float, TanHalfFov)
        SHADER_PARAMETER(float, DepthAttenuation)
        SHADER_PARAMETER(float, DisplayMin)
        SHADER_PARAMETER(float, DisplayMax)
        SHADER_PARAMETER_RDG_TEXTURE(Texture2D, Segmentation)
        SHADER_PARAMETER_RDG_TEXTURE(Texture2D, Depth)
        SHADER_PARAMETER_RDG_TEXTURE(Texture2D, Normals)
        SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<ThermalSample>, Samples)
        SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<float2>, Temperatures)
        SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<uint2>, Cells)
        SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<ThermalReceiver>, Receivers)
        SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<ThermalProfile>, Profiles)
        SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<uint>, Candidates)
        SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<ThermalUniform>, UniformSurfaces)
        SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<float>, RadianceLut)
        SHADER_PARAMETER_RDG_TEXTURE_UAV(RWTexture2D<float>, GrayOutput)
    END_SHADER_PARAMETER_STRUCT()
    static bool ShouldCompilePermutation(const FGlobalShaderPermutationParameters& P)
    { return IsFeatureLevelSupported(P.Platform, ERHIFeatureLevel::SM5); }
};
IMPLEMENT_GLOBAL_SHADER(FThermalResolveCS, "/Plugin/AirSimThermalGpu/Private/ThermalPreview.usf", "ThermalResolveCS", SF_Compute);

class FThermalDisplayCS : public FGlobalShader
{
public:
    DECLARE_GLOBAL_SHADER(FThermalDisplayCS);
    SHADER_USE_PARAMETER_STRUCT(FThermalDisplayCS, FGlobalShader);
    BEGIN_SHADER_PARAMETER_STRUCT(FParameters, )
        SHADER_PARAMETER(FIntPoint, ImageSize)
        SHADER_PARAMETER_RDG_TEXTURE(Texture2D, GrayInput)
        SHADER_PARAMETER_RDG_TEXTURE_UAV(RWTexture2D<float4>, DisplayOutput)
    END_SHADER_PARAMETER_STRUCT()
    static bool ShouldCompilePermutation(const FGlobalShaderPermutationParameters& P)
    { return IsFeatureLevelSupported(P.Platform, ERHIFeatureLevel::SM5); }
};
IMPLEMENT_GLOBAL_SHADER(FThermalDisplayCS, "/Plugin/AirSimThermalGpu/Private/ThermalPreview.usf", "ThermalDisplayCS", SF_Compute);

struct FThermalGpuRenderState
{
    // GPU resource ownership is render-thread-only, even after HUD teardown.
    TRefCountPtr<FRDGPooledBuffer> Samples, Cells, Temperatures, Profiles, Candidates, Radiance;
    uint64 GeometryRevision = 0, TemperatureRevision = 0, ProfileRevision = 0;
    std::atomic<uint64> Submitted{0}, Dispatched{0}, Skipped{0}, GeometryUploads{0}, TemperatureUploads{0};
    std::atomic<uint64> ResidentBytes{0};
};

FThermalGpuRenderer::FThermalGpuRenderer() : State(MakeShared<FThermalGpuRenderState, ESPMode::ThreadSafe>()) {}
bool FThermalGpuRenderer::IsSupported() { return !GUsingNullRHI && GMaxRHIFeatureLevel >= ERHIFeatureLevel::SM5; }

bool FThermalGpuRenderer::Render(FThermalGpuFrame&& Frame,
    TSharedPtr<const TArray<FThermalGpuProfile>, ESPMode::ThreadSafe> Profiles, uint64 ProfileRevision,
    TSharedPtr<const TArray<float>, ESPMode::ThreadSafe> Radiance,
    const FTransform& Camera, float Fov, FIntPoint Size, float Min, float Max, float Attenuation,
    FTextureRenderTargetResource* Seg, FTextureRenderTargetResource* Depth,
    FTextureRenderTargetResource* Normals, FTextureRenderTargetResource* Output, bool PackedInputs)
{
    check(IsInGameThread());
    if (!IsSupported() || !Frame.Topology || !Frame.Temperatures || !Profiles || !Radiance || !Seg || !Depth || !Normals || !Output) return false;
    if (Size.X <= 0 || Size.Y <= 0 || Size.X > 8192 || Size.Y > 8192 || Size != Output->GetSizeXY() ||
        Size != Seg->GetSizeXY() || Size != Depth->GetSizeXY() || Size != Normals->GetSizeXY()) {
        ++State->Skipped; return false;
    }
    // Bound pending render commands instead of accumulating RAM work on a hitch.
    if (State->Submitted.load() - State->Dispatched.load() >= 2) { ++State->Skipped; return false; }
    if (!ObjectTable || CachedProfileRevision != ProfileRevision || ProfileTopologyRevision != Frame.Topology->Revision) {
        ObjectTable = MakeShared<TArray<FThermalGpuProfile>, ESPMode::ThreadSafe>();
        CandidateTable = MakeShared<TArray<uint32>, ESPMode::ThreadSafe>();
        ObjectTable->SetNumZeroed(FMath::RoundUpToPowerOfTwo(FMath::Max(2u, uint32(Profiles->Num() + Frame.ReceiversByColor.Num()) * 2)));
        for (auto& Entry : *ObjectTable) Entry.Identity.X = MAX_uint32;
        const auto Find = [this](uint32 Key) -> FThermalGpuProfile& {
            uint32 Slot = ThermalGpuData::HashColor(Key) & (ObjectTable->Num() - 1);
            while ((*ObjectTable)[Slot].Identity.X != MAX_uint32 && (*ObjectTable)[Slot].Identity.X != Key)
                Slot = (Slot + 1) & (ObjectTable->Num() - 1);
            return (*ObjectTable)[Slot];
        };
        for (const auto& Profile : *Profiles) Find(Profile.Identity.X) = Profile;
        for (const auto& Pair : Frame.ReceiversByColor) {
            auto& Entry = Find(Pair.Key);
            if (Entry.Identity.X == MAX_uint32) { Entry.Identity.X = Pair.Key; Entry.Values = FVector4f(295, .9, 0, 0); }
            Entry.Identity.Y = CandidateTable->Num(); Entry.Identity.Z = Pair.Value.Num();
            CandidateTable->Append(Pair.Value);
        }
        CachedProfileRevision = ProfileRevision;
        ProfileTopologyRevision = Frame.Topology->Revision;
    }
    ++State->Submitted;
    ENQUEUE_RENDER_COMMAND(AirSimThermalGpuPreview)(
        [SharedState = State, Frame = MoveTemp(Frame), Table = ObjectTable, CandidateIds = CandidateTable,
         Lut = MoveTemp(Radiance), ProfileRevision, Camera, Fov, Size, Min, Max, Attenuation, Seg, Depth, Normals, Output, PackedInputs](FRHICommandListImmediate& RHICmdList) {
        const FTextureRHIRef SegRhi = Seg->GetRenderTargetTexture();
        const FTextureRHIRef DepthRhi = Depth->GetRenderTargetTexture();
        const FTextureRHIRef NormalRhi = Normals->GetRenderTargetTexture();
        const FTextureRHIRef OutputRhi = Output->GetRenderTargetTexture();
        if (!SegRhi || !DepthRhi || !NormalRhi || !OutputRhi) { ++SharedState->Dispatched; return; }
        FRDGBuilder Graph(RHICmdList);
        const bool NewGeometry = !SharedState->Samples || SharedState->GeometryRevision != Frame.Topology->Revision;
        FRDGBufferRef Samples, Cells, Temperatures, ProfileTable, CandidateBuffer, RadianceBuffer;
        if (NewGeometry) {
            Samples = CreateStructuredBuffer(Graph, TEXT("Thermal.Samples"), Frame.Topology->Samples, ERDGInitialDataFlags::NoCopy);
            Cells = CreateStructuredBuffer(Graph, TEXT("Thermal.Cells"), Frame.Topology->Cells, ERDGInitialDataFlags::NoCopy);
            Graph.QueueBufferExtraction(Samples, &SharedState->Samples);
            Graph.QueueBufferExtraction(Cells, &SharedState->Cells);
            SharedState->GeometryRevision = Frame.Topology->Revision;
            ++SharedState->GeometryUploads;
        } else {
            Samples = Graph.RegisterExternalBuffer(SharedState->Samples);
            Cells = Graph.RegisterExternalBuffer(SharedState->Cells);
        }
        if (NewGeometry || !SharedState->Temperatures || SharedState->TemperatureRevision != Frame.Temperatures->Revision) {
            Temperatures = CreateStructuredBuffer(Graph, TEXT("Thermal.Temperatures"), Frame.Temperatures->Values, ERDGInitialDataFlags::NoCopy);
            Graph.QueueBufferExtraction(Temperatures, &SharedState->Temperatures);
            SharedState->TemperatureRevision = Frame.Temperatures->Revision;
            ++SharedState->TemperatureUploads;
        } else Temperatures = Graph.RegisterExternalBuffer(SharedState->Temperatures);
        if (NewGeometry || !SharedState->Profiles || SharedState->ProfileRevision != ProfileRevision) {
            ProfileTable = CreateStructuredBuffer(Graph, TEXT("Thermal.Profiles"), *Table, ERDGInitialDataFlags::NoCopy);
            CandidateBuffer = CreateStructuredBuffer(Graph, TEXT("Thermal.Candidates"), *CandidateIds, ERDGInitialDataFlags::NoCopy);
            Graph.QueueBufferExtraction(ProfileTable, &SharedState->Profiles);
            Graph.QueueBufferExtraction(CandidateBuffer, &SharedState->Candidates);
            SharedState->ProfileRevision = ProfileRevision;
        } else {
            ProfileTable = Graph.RegisterExternalBuffer(SharedState->Profiles);
            CandidateBuffer = Graph.RegisterExternalBuffer(SharedState->Candidates);
        }
        if (!SharedState->Radiance) {
            RadianceBuffer = CreateStructuredBuffer(Graph, TEXT("Thermal.Radiance"), *Lut, ERDGInitialDataFlags::NoCopy);
            Graph.QueueBufferExtraction(RadianceBuffer, &SharedState->Radiance);
        } else RadianceBuffer = Graph.RegisterExternalBuffer(SharedState->Radiance);
        auto* P = Graph.AllocParameters<FThermalResolveCS::FParameters>();
        P->ImageSize = Size;
        P->ProfileMask = Table->Num() - 1;
        P->UniformCount = Frame.UniformSurfaces.Num();
        P->InputSrgbMask = (EnumHasAnyFlags(SegRhi->GetDesc().Flags, TexCreate_SRGB) ? 1u : 0u) |
            (EnumHasAnyFlags(NormalRhi->GetDesc().Flags, TexCreate_SRGB) ? 2u : 0u) | (PackedInputs ? 4u : 0u);
        P->CameraOrigin = FVector4f(FVector3f(Camera.GetLocation()), 0);
        P->CameraForward = FVector4f(FVector3f(Camera.GetUnitAxis(EAxis::X)), 0);
        P->CameraRight = FVector4f(FVector3f(Camera.GetUnitAxis(EAxis::Y)), 0);
        P->CameraUp = FVector4f(FVector3f(Camera.GetUnitAxis(EAxis::Z)), 0);
        P->TanHalfFov = FMath::Tan(FMath::DegreesToRadians(Fov) * .5f);
        P->DepthAttenuation = Attenuation; P->DisplayMin = Min; P->DisplayMax = Max;
        P->Segmentation = Graph.RegisterExternalTexture(CreateRenderTarget(SegRhi, TEXT("Thermal.Segmentation")));
        P->Depth = Graph.RegisterExternalTexture(CreateRenderTarget(DepthRhi, TEXT("Thermal.Depth")));
        P->Normals = Graph.RegisterExternalTexture(CreateRenderTarget(NormalRhi, TEXT("Thermal.Normals")));
        P->Samples = Graph.CreateSRV(Samples); P->Cells = Graph.CreateSRV(Cells); P->Temperatures = Graph.CreateSRV(Temperatures);
        P->Profiles = Graph.CreateSRV(ProfileTable); P->Candidates = Graph.CreateSRV(CandidateBuffer); P->RadianceLut = Graph.CreateSRV(RadianceBuffer);
        P->Receivers = Graph.CreateSRV(CreateStructuredBuffer(Graph, TEXT("Thermal.Receivers"), Frame.Receivers, ERDGInitialDataFlags::NoCopy));
        P->UniformSurfaces = Graph.CreateSRV(CreateStructuredBuffer(Graph, TEXT("Thermal.UniformSurfaces"), Frame.UniformSurfaces, ERDGInitialDataFlags::NoCopy));
        auto Gray = Graph.CreateTexture(FRDGTextureDesc::Create2D(Size, PF_R32_FLOAT, FClearValueBinding::None, TexCreate_ShaderResource | TexCreate_UAV), TEXT("Thermal.Gray"));
        P->GrayOutput = Graph.CreateUAV(Gray);
        auto ShaderMap = GetGlobalShaderMap(GMaxRHIFeatureLevel);
        TShaderMapRef<FThermalResolveCS> ResolveShader(ShaderMap);
        FComputeShaderUtils::AddPass(Graph, RDG_EVENT_NAME("AirSim Thermal surface/radiance"), ResolveShader, P, FComputeShaderUtils::GetGroupCount(Size, FIntPoint(8, 8)));
        auto Destination = Graph.RegisterExternalTexture(CreateRenderTarget(OutputRhi, TEXT("Thermal.Display")));
        auto* Display = Graph.AllocParameters<FThermalDisplayCS::FParameters>();
        Display->ImageSize = Size; Display->GrayInput = Gray; Display->DisplayOutput = Graph.CreateUAV(Destination);
        TShaderMapRef<FThermalDisplayCS> DisplayShader(ShaderMap);
        FComputeShaderUtils::AddPass(Graph, RDG_EVENT_NAME("AirSim Thermal optics/display"), DisplayShader, Display, FComputeShaderUtils::GetGroupCount(Size, FIntPoint(8, 8)));
        Graph.SetTextureAccessFinal(Destination, ERHIAccess::SRVMask);
        Graph.Execute();
        SharedState->ResidentBytes = uint64(Frame.Topology->Samples.Num()) * sizeof(FThermalGpuSample) +
            uint64(Frame.Topology->Cells.Num()) * sizeof(FThermalGpuCellRange) + uint64(Frame.Temperatures->Values.Num()) * sizeof(FVector2f) +
            uint64(Table->Num()) * sizeof(FThermalGpuProfile) + uint64(CandidateIds->Num()) * sizeof(uint32) + Lut->Num() * sizeof(float) + uint64(Size.X) * Size.Y * 12;
        ++SharedState->Dispatched;
    });
    return true;
}
FString FThermalGpuRenderer::GetStats() const
{
    return FString::Printf(TEXT("{\"submitted\":%llu,\"dispatched\":%llu,\"skipped\":%llu,\"geometry_uploads\":%llu,\"temperature_uploads\":%llu,\"gpu_data_bytes\":%llu}"),
        State->Submitted.load(), State->Dispatched.load(), State->Skipped.load(), State->GeometryUploads.load(), State->TemperatureUploads.load(), State->ResidentBytes.load());
}

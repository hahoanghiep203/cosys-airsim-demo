#include "SimHUD.h"
#include "UObject/ConstructorHelpers.h"
#include "Kismet/KismetSystemLibrary.h"
#include "Misc/FileHelper.h"

#include "Vehicles/Multirotor/SimModeWorldMultiRotor.h"
#include "Vehicles/Car/SimModeCar.h"
#include "Vehicles/SkidSteer/SimModeSkidVehicle.h"
#include "Vehicles/ComputerVision/SimModeComputerVision.h"

#include "Async/Async.h"
#include "Engine/Texture2D.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/PlanarReflectionComponent.h"
#include "UnrealImageCapture.h"
#include "HAL/IConsoleManager.h"
#include "ThermalWorldSubsystem.h"
#include "SyntheticCameraProcessor.h"
#include "Engine/TextureRenderTarget2D.h"
#include "ImageUtils.h"
#include "Engine/GameViewportClient.h"
#include "Slate/SceneViewport.h"
#include "Materials/MaterialInterface.h"

static TAutoConsoleVariable<float> ThermalLiveHz(TEXT("airsim.Thermal.LiveHz"), 30.f,
    TEXT("ThermalIR preview refresh rate (0 disables preview requests; 1-60 Hz). Does not change thermal simulation or RPC captures."));
static TAutoConsoleVariable<int32> ThermalGpuPreview(TEXT("airsim.Thermal.GpuPreview"), 1,
    TEXT("GPU-resident ThermalIR on SM5+ hardware. 0 uses the CPU reference. Explicit RPC requests read back a fresh GPU image."));
static TAutoConsoleVariable<float> RgbPreviewHz(TEXT("airsim.Camera.RgbPreviewHz"), 30.f,
    TEXT("Displayed RGB camera preview refresh rate (0 pauses camera previews; 1-60 Hz). Main viewport and explicit RPC captures are independent."));
static TAutoConsoleVariable<int32> PlanarReflectionBudget(TEXT("airsim.Rendering.PlanarReflectionBudget"), 0,
    TEXT("Opt-in runtime reflection budget: 25 percent resolution, coarser reflected LODs and 50 m range. Original map assets remain unchanged; set before Play."));

#include "common/AirSimSettings.hpp"
#include <stdexcept>

ASimHUD::ASimHUD()
{
    static ConstructorHelpers::FClassFinder<UUserWidget> hud_widget_class(TEXT("WidgetBlueprint'/AirSim/Blueprints/BP_SimHUDWidget'"));
    widget_class_ = hud_widget_class.Succeeded() ? hud_widget_class.Class : nullptr;
}

void ASimHUD::BeginPlay()
{
    Super::BeginPlay();

    if (PlanarReflectionBudget.GetValueOnGameThread()) {
        for (TObjectIterator<UPlanarReflectionComponent> It; It; ++It) {
            auto* Reflection = *It;
            if (Reflection->GetWorld() != GetWorld()) continue;
            Reflection->ScreenPercentage = FMath::Min(Reflection->ScreenPercentage, 25);
            Reflection->LODDistanceFactor = FMath::Max(Reflection->LODDistanceFactor, 4.f);
            Reflection->MaxViewDistanceOverride = Reflection->MaxViewDistanceOverride > 0
                ? FMath::Min(Reflection->MaxViewDistanceOverride, 5000.f) : 5000.f;
        }
    }

    try {
        UAirBlueprintLib::OnBeginPlay();
        initializeSettings();
        loadLevel();

        // Prevent a MavLink connection being established if changing levels
        if (map_changed_) return;

        setUnrealEngineSettings();
        createSimMode();
        createMainWidget();
        setupInputBindings();
        if (simmode_)
            simmode_->startApiServer();
    }
    catch (std::exception& ex) {
        UAirBlueprintLib::LogMessageString("Error at startup: ", ex.what(), LogDebugLevel::Failure);
        //FGenericPlatformMisc::PlatformInit();
        //FGenericPlatformMisc::MessageBoxExt(EAppMsgType::Ok, TEXT("Error at Startup"), ANSI_TO_TCHAR(ex.what()));
        UAirBlueprintLib::ShowMessage(EAppMsgType::Ok, std::string("Error at startup: ") + ex.what(), "Error");
    }
}

void ASimHUD::Tick(float DeltaSeconds)
{
    if (simmode_ && simmode_->EnableReport)
        widget_->updateDebugReport(simmode_->getDebugReport());

    // ---------------------------------------------------------
    // Live ThermalIR window
    // ---------------------------------------------------------
    if (!simmode_ || !widget_)
        return;

    // A visible RGB camera window otherwise renders the scene a second time
    // at the main viewport's full frame rate. Schedule it independently.
    const float RgbHz = RgbPreviewHz.GetValueOnGameThread();
    const float RgbInterval = 1.f / FMath::Clamp(RgbHz, 1.f, 60.f);
    rgb_live_elapsed_ += DeltaSeconds;
    const bool CaptureRgb = RgbHz > 0 && rgb_live_elapsed_ >= RgbInterval;
    if (CaptureRgb) rgb_live_elapsed_ = FMath::Fmod(rgb_live_elapsed_, RgbInterval);
    for (int32 Index = 0; Index < getSubWindowSettings().size(); ++Index) {
        const auto& Window = getSubWindowSettings()[Index];
        if (!Window.visible || Window.image_type != ImageType::Scene || !subwindow_cameras_[Index]) continue;
        auto* Capture = subwindow_cameras_[Index]->getCaptureComponent(ImageType::Scene, true);
        if (!Capture) continue;
        Capture->bCaptureEveryFrame = false;
        Capture->bCaptureOnMovement = false;
        if (CaptureRgb) Capture->CaptureSceneDeferred();
    }

    if (getSubWindowSettings().size() <= 3)
        return;

    const auto& thermal_window =
        getSubWindowSettings().at(3);

    if (thermal_window.image_type != ImageType::ThermalIR ||
        !thermal_window.visible)
    {
        return;
    }

    const float LiveHz = ThermalLiveHz.GetValueOnGameThread();
    if (LiveHz <= 0) return;
    thermal_live_interval_ = 1.f / FMath::Clamp(LiveHz, 1.f, 60.f);
    thermal_live_elapsed_ += DeltaSeconds;

    if (thermal_live_elapsed_ >= thermal_live_interval_)
    {
        thermal_live_elapsed_ = FMath::Fmod(thermal_live_elapsed_, thermal_live_interval_);

        if (ThermalGpuPreview.GetValueOnGameThread() && FThermalGpuRenderer::IsSupported() && requestThermalGpuFrame()) return;

        if (!thermal_request_in_flight_.exchange(true))
        {
            requestThermalLiveFrame();
        }
    }
}

void ASimHUD::restoreThermalStencil()
{
    for (const auto& Entry : thermal_stencil_restore_) if (Entry.Component.IsValid()) {
        auto* C = Entry.Component.Get();
        C->SetRenderCustomDepth(Entry.Enabled);
        C->SetCustomDepthStencilValue(Entry.Value);
        C->SetCustomDepthStencilWriteMask(Entry.Mask);
    }
    thermal_stencil_restore_.Reset();
    thermal_stencil_seen_.Reset();
}

bool ASimHUD::prepareThermalGpuFrame(APIPCamera* Camera)
{
    if (!IsValid(Camera) || !FThermalGpuRenderer::IsSupported() || !simmode_) return false;
    const auto* Depth = Camera->getCaptureComponent(ImageType::DepthPlanar, false);
    // Inactive AirSim captures detach their TextureTarget. Camera settings and
    // the allocated target remain available without enabling another renderer.
    const auto* DepthTarget = Camera->getRenderTarget(ImageType::DepthPlanar, false);
    if (!Depth || !DepthTarget || Depth->ProjectionType != ECameraProjectionMode::Perspective) return false;
    const FIntPoint Size(DepthTarget->SizeX, DepthTarget->SizeY);
    if (Size.X <= 0 || Size.Y <= 0 || Size.X > 8192 || Size.Y > 8192) return false;
    const FTransform Transform = Depth->GetComponentTransform();
    uint64 Revision = 0;
    const auto Profiles = SyntheticCameraProcessor::instance().gpuThermalProfiles(Transform.GetLocation(), Transform.GetUnitAxis(EAxis::X),
        FMath::Tan(FMath::DegreesToRadians(Depth->FOVAngle) * .5f), float(Size.X) / Size.Y, Revision);
    if (!Profiles) return false;
    auto Frame = GetWorld()->GetSubsystem<UThermalWorldSubsystem>()->MakeGpuFrame();
    if (!Frame.Topology) return false;
    if (!thermal_packed_profiles_ || Revision != thermal_source_profile_revision_ ||
        Frame.Topology->Revision != thermal_source_topology_revision_) {
        TMap<uint32, FVector4f> Values;
        for (const auto& P : *Profiles) Values.Add(P.Identity.X, P.Values);
        const auto Colors = simmode_->GetInstanceSegmentationComponentColors();
        TMap<FString, uint32> Groups;
        auto NewProfiles = MakeShared<TArray<FThermalGpuProfile>, ESPMode::ThreadSafe>();
        TMap<uint32, uint32> NewIds;
        struct FAssignment { UPrimitiveComponent* C; uint32 Id; };
        TArray<FAssignment> Assignments;
        for (const auto& Pair : Colors) {
            auto* C = Pair.Key;
            if (!IsValid(C)) continue;
            if (C->ComponentHasTag(TEXT("ThermalIgnore")) || C->GetOwner()->ActorHasTag(TEXT("ThermalIgnore"))) {
                Assignments.Add({C, 0}); continue;
            }
            // Translucent puddle/glass planes are absent from opaque scene depth.
            // Their entire quad must not mask the road or another surface behind.
            bool HasSurface = false;
            for (int32 M = 0; M < C->GetNumMaterials(); ++M) if (auto* Material = C->GetMaterial(M)) {
                const auto Blend = Material->GetBlendMode();
                HasSurface |= Blend == BLEND_Opaque || Blend == BLEND_Masked;
            }
            if (!HasSurface) { Assignments.Add({C, 0}); continue; }
            const uint32 Color = (uint32(Pair.Value.R) << 16) | (uint32(Pair.Value.G) << 8) | Pair.Value.B;
            const auto* Profile = Values.Find(Color);
            if (!Profile) continue;
            // A heated receiver needs its own identity. Uniform cold objects can
            // share an ID only when both temperature and emissivity match.
            const FString Group = Frame.ReceiversByColor.Contains(Color) ? FString::Printf(TEXT("receiver:%u"), Color) :
                FString::Printf(TEXT("baseline:%.6f:%.6f"), Profile->X, Profile->Y);
            uint32* Existing = Groups.Find(Group);
            uint32 Id = Existing ? *Existing : NewProfiles->Num() + 1;
            if (!Existing) {
                if (Id > 255) return false; // Retain the full-identity CPU fallback.
                Groups.Add(Group, Id);
                NewProfiles->Add({FUintVector4(Id << 16, 0, 0, 0), *Profile});
            }
            NewIds.Add(Color, Id);
            Assignments.Add({C, Id});
        }
        // Runtime-only stencil changes: keep original state for every component
        // and restore it at EndPlay. Mesh/material/map assets are never modified.
        for (const auto& Assignment : Assignments) {
            auto* C = Assignment.C;
            if (!thermal_stencil_seen_.Contains(C)) {
                thermal_stencil_restore_.Add({C, bool(C->bRenderCustomDepth), C->CustomDepthStencilValue, C->CustomDepthStencilWriteMask});
                thermal_stencil_seen_.Add(C);
            }
            C->SetRenderCustomDepth(Assignment.Id != 0);
            // Default writes IDs only where this surface wins the depth test.
            // ERSM_255 also replaces stencil on a failed depth test, letting
            // background roads overwrite the IDs of a car or a lamp in front.
            C->SetCustomDepthStencilWriteMask(ERendererStencilMask::ERSM_Default);
            C->SetCustomDepthStencilValue(Assignment.Id);
        }
        thermal_packed_ids_ = MoveTemp(NewIds);
        thermal_packed_profiles_ = MoveTemp(NewProfiles);
        thermal_source_profile_revision_ = Revision;
        thermal_source_topology_revision_ = Frame.Topology->Revision;
        ++thermal_packed_revision_;
    }
    TMap<uint32, TArray<uint32>> Remapped;
    for (const auto& Pair : Frame.ReceiversByColor) if (const auto* Id = thermal_packed_ids_.Find(Pair.Key))
        Remapped.FindOrAdd(*Id << 16).Append(Pair.Value);
    Frame.ReceiversByColor = MoveTemp(Remapped);
    if (!thermal_gpu_renderer_) thermal_gpu_renderer_ = MakeUnique<FThermalGpuRenderer>();
    if (!thermal_gpu_inputs_) thermal_gpu_inputs_ = MakeUnique<FThermalGpuInputs>();
    if (!thermal_geometry_capture_) {
        thermal_geometry_capture_ = NewObject<USceneCaptureComponent2D>(this);
        thermal_geometry_capture_->RegisterComponentWithWorld(GetWorld());
        thermal_geometry_capture_->bCaptureEveryFrame = thermal_geometry_capture_->bCaptureOnMovement = false;
        thermal_geometry_capture_->bAlwaysPersistRenderingState = true;
        thermal_geometry_capture_->CaptureSource = ESceneCaptureSource::SCS_FinalColorLDR;
        auto& Flags = thermal_geometry_capture_->ShowFlags;
        Flags.SetDynamicShadows(false); Flags.SetGlobalIllumination(false); Flags.SetReflectionEnvironment(false);
        Flags.SetAmbientOcclusion(false); Flags.SetFog(false); Flags.SetVolumetricFog(false); Flags.SetAtmosphere(false);
        Flags.SetLighting(false); Flags.SetTemporalAA(false); Flags.SetMotionBlur(false); Flags.SetBloom(false);
        Flags.SetEyeAdaptation(false); Flags.SetDecals(false);
        // FinalColor captures do not take UE's automatic unlit optimization.
        // Rich-view mode forces expensive dynamic mesh drawing in this large
        // scene; keep the ordinary cached draw path for geometry-only inputs.
        Flags.SetUnlitRichView(false); Flags.SetUnlitViewmode(false);
        Flags.SetScreenSpaceReflections(false);
        Flags.SetRefraction(false); Flags.SetLightFunctions(false); Flags.SetSkyLighting(false);
        // Inputs are opaque/masked depth and normals; translucent color is unused.
        Flags.SetTranslucency(false);
        Flags.SetAntiAliasing(false); Flags.SetLensFlares(false);
        // Use actual meshes/material masks; annotation proxies are not camera geometry.
    }
    // Annotation components normally hide themselves when Materials is enabled.
    // Also exclude them explicitly so every proxy type remains safe.
    thermal_geometry_capture_->HiddenComponents = Camera->getCaptureComponent(ImageType::Scene, false)->HiddenComponents;
    // Route demo markers may be visible in the fixed observer, but must never
    // occlude drone RGB or thermal geometry. Mirror the camera exclusion list.
    thermal_geometry_capture_->HiddenActors = Camera->getCaptureComponent(ImageType::Scene, false)->HiddenActors;
    const auto MakeTarget = [this, Size](UTextureRenderTarget2D*& Target, EPixelFormat Format) {
        if (Target && Target->SizeX == Size.X && Target->SizeY == Size.Y) return;
        Target = NewObject<UTextureRenderTarget2D>(this);
        Target->bSupportsUAV = true; Target->ClearColor = FLinearColor::Black;
        Target->Filter = TF_Bilinear;
        Target->InitCustomFormat(Size.X, Size.Y, Format, true);
        Target->UpdateResourceImmediate(true);
    };
    MakeTarget(thermal_gpu_texture_, PF_FloatRGBA);
    MakeTarget(thermal_geometry_target_, PF_FloatRGBA);
    MakeTarget(thermal_identity_target_, PF_R8G8B8A8);
    MakeTarget(thermal_camera_target_, PF_FloatRGBA);
    thermal_geometry_capture_->TextureTarget = thermal_camera_target_;
    thermal_geometry_capture_->SetWorldTransform(Transform);
    thermal_geometry_capture_->FOVAngle = Depth->FOVAngle;
    thermal_gpu_inputs_->Configure(thermal_camera_target_->GameThread_GetRenderTargetResource(),
        thermal_geometry_target_->GameThread_GetRenderTargetResource(), thermal_identity_target_->GameThread_GetRenderTargetResource());
    thermal_pending_frame_ = MakeUnique<FThermalGpuFrame>(MoveTemp(Frame));
    thermal_pending_transform_ = Transform;
    thermal_pending_fov_ = Depth->FOVAngle;
    if (widget_ && getSubWindowSettings().size() > 3 && getSubWindowSettings()[3].visible &&
        thermal_bound_texture_.Get() != thermal_gpu_texture_) {
        widget_->setSubwindowVisibility(3, true, thermal_gpu_texture_);
        thermal_bound_texture_ = thermal_gpu_texture_;
    }
    return true;
}

bool ASimHUD::finishThermalGpuFrame()
{
    if (!thermal_pending_frame_ || !thermal_gpu_renderer_ || !thermal_gpu_texture_) return false;
    const auto& Config = AirSimSettings::singleton().synthetic_camera.thermal_ir;
    const float Min = FMath::IsFinite(Config.display_temp_min) ? FMath::Clamp(float(Config.display_temp_min), 1.f, 1998.f) : 280.f;
    const float Max = FMath::IsFinite(Config.display_temp_max) ? FMath::Clamp(float(Config.display_temp_max), Min + 1, 1999.f) : 380.f;
    const bool Result = thermal_gpu_renderer_->Render(MoveTemp(*thermal_pending_frame_), thermal_packed_profiles_, thermal_packed_revision_,
        SyntheticCameraProcessor::instance().gpuThermalRadiance(), thermal_pending_transform_, thermal_pending_fov_,
        FIntPoint(thermal_gpu_texture_->SizeX, thermal_gpu_texture_->SizeY), Min, Max, Config.depth_attenuation,
        thermal_identity_target_->GameThread_GetRenderTargetResource(), thermal_geometry_target_->GameThread_GetRenderTargetResource(),
        thermal_geometry_target_->GameThread_GetRenderTargetResource(), thermal_gpu_texture_->GameThread_GetRenderTargetResource(), true);
    thermal_pending_frame_.Reset();
    return Result;
}

bool ASimHUD::requestThermalGpuFrame()
{
    if (thermal_request_in_flight_.load() || thermal_gpu_end_draw_.IsValid()) return true;
    auto* Viewport = GetWorld()->GetGameViewport();
    if (!Viewport || !prepareThermalGpuFrame(subwindow_cameras_[3])) return false;
    thermal_geometry_capture_->CaptureSceneDeferred();
    thermal_gpu_viewport_ = Viewport;
    TWeakObjectPtr<ASimHUD> WeakThis(this);
    thermal_gpu_end_draw_ = Viewport->OnEndDraw().AddLambda([WeakThis]() {
        if (!WeakThis.IsValid()) return;
        auto* Hud = WeakThis.Get();
        if (Hud->thermal_gpu_viewport_.IsValid()) Hud->thermal_gpu_viewport_->OnEndDraw().Remove(Hud->thermal_gpu_end_draw_);
        Hud->thermal_gpu_end_draw_.Reset();
        Hud->finishThermalGpuFrame();
    });
    return true;
}

bool ASimHUD::captureThermalGpuImage(APIPCamera* Camera, TArray<FColor>& Pixels, int32& Width, int32& Height)
{
    check(IsInGameThread());
    if (!ThermalGpuPreview.GetValueOnGameThread()) return false;
    if (thermal_gpu_viewport_.IsValid() && thermal_gpu_end_draw_.IsValid())
        thermal_gpu_viewport_->OnEndDraw().Remove(thermal_gpu_end_draw_);
    thermal_gpu_end_draw_.Reset();
    if (!prepareThermalGpuFrame(Camera)) return false;
    thermal_geometry_capture_->CaptureScene();
    if (!finishThermalGpuFrame()) return false;
    FReadSurfaceDataFlags Flags(RCM_UNorm); Flags.SetLinearToGamma(true);
    Width = thermal_gpu_texture_->SizeX; Height = thermal_gpu_texture_->SizeY;
    // Only an explicit API/export request reads the completed GPU image to RAM.
    return thermal_gpu_texture_->GameThread_GetRenderTargetResource()->ReadPixels(Pixels, Flags);
}
FString ASimHUD::getThermalGpuStats() const
{
    const auto* Client = GetWorld() ? GetWorld()->GetGameViewport() : nullptr;
    const auto* Viewport = Client ? Client->GetGameViewport() : nullptr;
    const FIntPoint MainSize = Viewport ? Viewport->GetRenderTargetTextureSizeXY() : FIntPoint::ZeroValue;
    FString Stats = thermal_gpu_renderer_ ? thermal_gpu_renderer_->GetStats() : TEXT("{}");
    Stats.LeftChopInline(1);
    if (Stats.Len() > 1) Stats += TEXT(",");
    Stats += FString::Printf(TEXT("\"input_captures\":%llu,\"profile_groups\":%d,\"main_width\":%d,\"main_height\":%d}"),
        thermal_gpu_inputs_ ? thermal_gpu_inputs_->GetCaptureCount() : 0, thermal_packed_profiles_ ? thermal_packed_profiles_->Num() : 0,
        MainSize.X, MainSize.Y);
    return Stats;
}
bool ASimHUD::setThermalReviewViewportSize(int32 Width, int32 Height)
{
    if (Width < 0 || Height < 0 || Width > 8192 || Height > 8192 || (Width == 0) != (Height == 0)) return false;
    auto* Client = GetWorld() ? GetWorld()->GetGameViewport() : nullptr;
    auto* Viewport = Client ? Client->GetGameViewport() : nullptr;
    if (!Viewport) return false;
    Viewport->SetFixedViewportSize(Width, Height);
    thermal_review_fixed_viewport_ = Width > 0;
    return true;
}
bool ASimHUD::saveThermalGpuPreview(const FString& Path)
{
    if (!thermal_gpu_texture_) return false;
    TArray<FColor> Pixels;
    FReadSurfaceDataFlags Flags(RCM_UNorm);
    Flags.SetLinearToGamma(true);
    if (!thermal_gpu_texture_->GameThread_GetRenderTargetResource()->ReadPixels(Pixels, Flags)) return false;
    TArray<uint8> Png;
    FImageUtils::CompressImageArray(thermal_gpu_texture_->SizeX, thermal_gpu_texture_->SizeY, Pixels, Png);
    return FFileHelper::SaveArrayToFile(Png, *Path);
}

bool ASimHUD::saveThermalCpuReference(const FString& Path)
{
    // Diagnostic only: independently run the established CPU surface/radiance
    // calculation on the same corrected opaque/masked camera inputs.
    if (!thermal_geometry_target_ || !thermal_identity_target_ || !thermal_packed_profiles_) return false;
    TArray<FFloat16Color> Geometry;
    TArray<FColor> Identity;
    FReadSurfaceDataFlags Flags(RCM_UNorm); Flags.SetLinearToGamma(false);
    if (!thermal_geometry_target_->GameThread_GetRenderTargetResource()->ReadFloat16Pixels(Geometry) ||
        !thermal_identity_target_->GameThread_GetRenderTargetResource()->ReadPixels(Identity, Flags)) return false;
    const int32 W = thermal_geometry_target_->SizeX, H = thermal_geometry_target_->SizeY;
    if (Geometry.Num() != W * H || Identity.Num() != W * H) return false;
    std::vector<float> Depth(W * H), Temperature, Emissivity;
    std::vector<uint8_t> Seg(W * H * 3, 0), Normals(W * H * 3);
    for (int32 P = 0; P < Geometry.Num(); ++P) {
        Depth[P] = Geometry[P].A.GetFloat(); Seg[P * 3] = Identity[P].R;
        Normals[P * 3] = FMath::RoundToInt(FMath::Clamp(Geometry[P].R.GetFloat(), 0.f, 1.f) * 255);
        Normals[P * 3 + 1] = FMath::RoundToInt(FMath::Clamp(Geometry[P].G.GetFloat(), 0.f, 1.f) * 255);
        Normals[P * 3 + 2] = FMath::RoundToInt(FMath::Clamp(Geometry[P].B.GetFloat(), 0.f, 1.f) * 255);
    }
    auto Frame = GetWorld()->GetSubsystem<UThermalWorldSubsystem>()->MakeSnapshot();
    Frame.CameraTransform = thermal_pending_transform_;
    Frame.TanHalfHorizontalFov = FMath::Tan(FMath::DegreesToRadians(thermal_pending_fov_) * .5f);
    TMap<uint32, TArray<int32>> Remapped;
    for (const auto& Pair : Frame.ReceiversByColor) if (const auto* Id = thermal_packed_ids_.Find(Pair.Key))
        Remapped.FindOrAdd(*Id << 16).Append(Pair.Value);
    Frame.ReceiversByColor = MoveTemp(Remapped);
    Frame.ResolvePixels(Depth, W, H, Temperature, Emissivity, Normals, Seg);
    TMap<uint32, FVector4f> Profiles;
    for (const auto& P : *thermal_packed_profiles_) Profiles.Add(P.Identity.X, P.Values);
    for (int32 P = 0; P < W * H; ++P) if (!FMath::IsFinite(Temperature[P])) {
        const auto* Profile = Profiles.Find(uint32(Identity[P].R) << 16);
        Temperature[P] = Profile ? Profile->X : 295;
        Emissivity[P] = Profile ? Profile->Y : .9f;
        if (!FMath::IsFinite(Depth[P]) || Depth[P] <= 0 || Depth[P] > 1.e5f) { Temperature[P] = 270; Emissivity[P] = 1; }
    }
    std::vector<uint8_t> RGB;
    SyntheticCameraProcessor::instance().composeThermalIR(Seg, Depth, {}, Normals, W, H, RGB, Temperature, Emissivity);
    TArray<FColor> Pixels; Pixels.SetNumUninitialized(W * H);
    for (int32 P = 0; P < Pixels.Num(); ++P) Pixels[P] = FColor(RGB[P * 3], RGB[P * 3 + 1], RGB[P * 3 + 2], 255);
    TArray<uint8> Png; FImageUtils::CompressImageArray(W, H, Pixels, Png);
    return FFileHelper::SaveArrayToFile(Png, *Path);
}

void ASimHUD::requestThermalLiveFrame()
{
    if (!simmode_ || getSubWindowSettings().size() <= 3)
    {
        thermal_request_in_flight_ = false;
        return;
    }

    const auto thermal_setting =
        getSubWindowSettings().at(3);

    const UnrealImageCapture* image_capture =
        simmode_->getImageCapture(
            thermal_setting.vehicle_name
        );

    if (!image_capture)
    {
        thermal_request_in_flight_ = false;
        return;
    }

    const std::string camera_name =
        thermal_setting.camera_name;

    TWeakObjectPtr<ASimHUD> weak_this(this);

    Async(
        EAsyncExecution::ThreadPool,

        [weak_this,
         image_capture,
         camera_name]()
        {
            using ImageRequest =
                msr::airlib::ImageCaptureBase::ImageRequest;

            using ImageResponse =
                msr::airlib::ImageCaptureBase::ImageResponse;

            // using ImageType =
            //     msr::airlib::ImageCaptureBase::ImageType;

            std::vector<ImageRequest> requests;

            requests.emplace_back(
                camera_name,
                msr::airlib::ImageCaptureBase::ImageType::ThermalIR,
                false,
                false
            );

            std::vector<ImageResponse> responses;

            image_capture->getImages(
                requests,
                responses
            );

            if (responses.size() != 1)
            {
                AsyncTask(
                    ENamedThreads::GameThread,
                    [weak_this]()
                    {
                        if (weak_this.IsValid())
                            weak_this->thermal_request_in_flight_ = false;
                    }
                );

                return;
            }

            ImageResponse response =
                std::move(responses[0]);

            const int32 width =
                response.width;

            const int32 height =
                response.height;

            std::vector<uint8_t> rgb =
                std::move(response.image_data_uint8);

            AsyncTask(
                ENamedThreads::GameThread,

                [weak_this,
                 width,
                 height,
                 rgb = std::move(rgb)]() mutable
                {
                    if (!weak_this.IsValid())
                        return;

                    weak_this->updateThermalLiveTexture(
                        width,
                        height,
                        std::move(rgb)
                    );

                    weak_this->thermal_request_in_flight_ = false;
                }
            );
        }
    );
}

void ASimHUD::updateThermalLiveTexture(
    int32 width,
    int32 height,
    std::vector<uint8_t>&& rgb_data)
{
    if (width <= 0 || height <= 0)
        return;

    const size_t expected_size =
        static_cast<size_t>(width)
        * static_cast<size_t>(height)
        * 3;

    if (rgb_data.size() != expected_size)
        return;

    // ---------------------------------------------------------
    // Create the display texture on first frame,
    // or recreate it if resolution changed.
    // ---------------------------------------------------------
    if (!thermal_live_texture_ ||
        thermal_live_width_ != width ||
        thermal_live_height_ != height)
    {
        thermal_live_texture_ =
            UTexture2D::CreateTransient(
                width,
                height,
                PF_B8G8R8A8
            );

        if (!thermal_live_texture_)
            return;

        thermal_live_texture_->SRGB = true;
        thermal_live_texture_->NeverStream = true;
        thermal_live_texture_->Filter = TF_Bilinear;

        thermal_live_texture_->UpdateResource();

        thermal_live_width_ = width;
        thermal_live_height_ = height;
    }

    // ---------------------------------------------------------
    // Thermal processor returns RGB.
    // Unreal texture expects BGRA.
    // ---------------------------------------------------------
    const int32 pixel_count =
        width * height;

    uint8* bgra =
        new uint8[
            static_cast<size_t>(pixel_count) * 4
        ];

    for (int32 i = 0; i < pixel_count; ++i)
    {
        bgra[i * 4 + 0] =
            rgb_data[i * 3 + 2]; // B

        bgra[i * 4 + 1] =
            rgb_data[i * 3 + 1]; // G

        bgra[i * 4 + 2] =
            rgb_data[i * 3 + 0]; // R

        bgra[i * 4 + 3] =
            255;                 // A
    }

    FUpdateTextureRegion2D* region =
        new FUpdateTextureRegion2D(
            0,
            0,
            0,
            0,
            width,
            height
        );

    thermal_live_texture_->UpdateTextureRegions(
        0,
        1,
        region,
        width * 4,
        4,
        bgra,

        [](uint8* src_data,
           const FUpdateTextureRegion2D* regions)
        {
            delete[] src_data;
            delete regions;
        }
    );

    // ---------------------------------------------------------
    // Feed the generated texture into SubWindow 3.
    // ---------------------------------------------------------
    if (widget_ &&
        getSubWindowSettings().size() > 3 &&
        getSubWindowSettings().at(3).visible &&
        thermal_bound_texture_.Get() != thermal_live_texture_)
    {
        widget_->setSubwindowVisibility(
            3,
            true,
            thermal_live_texture_
        );
        thermal_bound_texture_ = thermal_live_texture_;
    }
}

void ASimHUD::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    if (thermal_review_fixed_viewport_) setThermalReviewViewportSize(0, 0);
    if (thermal_gpu_viewport_.IsValid() && thermal_gpu_end_draw_.IsValid())
        thermal_gpu_viewport_->OnEndDraw().Remove(thermal_gpu_end_draw_);
    thermal_gpu_end_draw_.Reset();
    thermal_gpu_inputs_.Reset();
    thermal_pending_frame_.Reset();
    restoreThermalStencil();
    thermal_gpu_renderer_.Reset();
    if (simmode_)
        simmode_->stopApiServer();

    if (widget_) {
        widget_->Destruct();
        widget_ = nullptr;
    }
    if (simmode_) {
        simmode_->Destroy();
        simmode_ = nullptr;
    }

    UAirBlueprintLib::OnEndPlay();

    Super::EndPlay(EndPlayReason);
}

void ASimHUD::toggleRecordHandler()
{
    simmode_->toggleRecording();
}

void ASimHUD::inputEventToggleRecording()
{
    toggleRecordHandler();
}

void ASimHUD::inputEventToggleReport()
{
    simmode_->EnableReport = !simmode_->EnableReport;
    widget_->setReportVisible(simmode_->EnableReport);
}

void ASimHUD::inputEventToggleHelp()
{
    widget_->toggleHelpVisibility();
}

void ASimHUD::inputEventToggleTrace()
{
    simmode_->toggleTraceAll();
}

void ASimHUD::updateWidgetSubwindowVisibility()
{
    for (int window_index = 0; window_index < AirSimSettings::kSubwindowCount; ++window_index) {
        APIPCamera* camera = subwindow_cameras_[window_index];
        ImageType camera_type = getSubWindowSettings().at(window_index).image_type;
        if (camera_type == ImageType::ThermalIR)
        {
            const bool is_visible =
                getSubWindowSettings()
                    .at(window_index)
                    .visible
                && camera != nullptr;

            UTexture* Display = ThermalGpuPreview.GetValueOnGameThread() && thermal_gpu_texture_
                ? static_cast<UTexture*>(thermal_gpu_texture_) : static_cast<UTexture*>(thermal_live_texture_);
            widget_->setSubwindowVisibility(
                window_index,
                is_visible,
                is_visible
                    ? Display
                    : nullptr
            );
            thermal_bound_texture_ = is_visible ? Display : nullptr;

            continue;
        }
		std::string annotation_name = getSubWindowSettings().at(window_index).annotation_name;

        if (camera_type == ImageType::Annotation) {
            if (simmode_->DoesAnnotationLayerExist(FString(annotation_name.c_str()))) {
                bool is_visible = getSubWindowSettings().at(window_index).visible && camera != nullptr;

                if (camera != nullptr) {
                    camera->setCameraTypeEnabled(camera_type, is_visible, annotation_name);
                    //sub-window captures don't count as a request, set bCaptureEveryFrame and bCaptureOnMovement to display so we can show correctly the subwindow
                    camera->setCameraTypeUpdate(camera_type, false, annotation_name);
                }

                widget_->setSubwindowVisibility(window_index,
                    is_visible,
                    is_visible ? camera->getRenderTarget(camera_type, false, annotation_name) : nullptr);
            }
        }
        else {
            bool is_visible = getSubWindowSettings().at(window_index).visible && camera != nullptr;

            if (camera != nullptr) {
                camera->setCameraTypeEnabled(camera_type, is_visible, annotation_name);
                //sub-window captures don't count as a request, set bCaptureEveryFrame and bCaptureOnMovement to display so we can show correctly the subwindow
                camera->setCameraTypeUpdate(camera_type, false, annotation_name);
            }

            widget_->setSubwindowVisibility(window_index,
                is_visible,
                is_visible ? camera->getRenderTarget(camera_type, false, annotation_name) : nullptr);
        }
    }
}

bool ASimHUD::isWidgetSubwindowVisible(int window_index)
{
    return widget_->getSubwindowVisibility(window_index) != 0;
}

void ASimHUD::toggleSubwindowVisibility(int window_index)
{
    getSubWindowSettings().at(window_index).visible = !getSubWindowSettings().at(window_index).visible;
    updateWidgetSubwindowVisibility();
}

void ASimHUD::inputEventToggleSubwindow0()
{
    toggleSubwindowVisibility(0);
}

void ASimHUD::inputEventToggleSubwindow1()
{
    toggleSubwindowVisibility(1);
}

void ASimHUD::inputEventToggleSubwindow2()
{
    toggleSubwindowVisibility(2);
}

void ASimHUD::inputEventToggleSubwindow3()
{
    toggleSubwindowVisibility(3);
}

void ASimHUD::inputEventToggleAll()
{
    const bool new_visibility =
        !getSubWindowSettings().at(0).visible;

    for (int i = 0;
         i < AirSimSettings::kSubwindowCount;
         ++i)
    {
        getSubWindowSettings().at(i).visible =
            new_visibility;
    }

    updateWidgetSubwindowVisibility();
}

void ASimHUD::createMainWidget()
{
    //create main widget
    if (widget_class_ != nullptr) {
        APlayerController* player_controller = this->GetWorld()->GetFirstPlayerController();
        TObjectPtr<APawn> pawn = player_controller->GetPawn();
        if (pawn) {
            std::string pawn_name = std::string(TCHAR_TO_ANSI(*pawn->GetName()));
            Utils::log(pawn_name);
        }
        else {
            UAirBlueprintLib::ShowMessage(EAppMsgType::Ok, std::string("There were no compatible vehicles created for current SimMode! Check your settings.json."), "Error");
            UAirBlueprintLib::LogMessage(TEXT("There were no compatible vehicles created for current SimMode! Check your settings.json."), TEXT(""), LogDebugLevel::Failure);
        }

        widget_ = CreateWidget<USimHUDWidget>(player_controller, widget_class_);
    }
    else {
        widget_ = nullptr;
        UAirBlueprintLib::LogMessage(TEXT("Cannot instantiate BP_SimHUDWidget blueprint!"), TEXT(""), LogDebugLevel::Failure);
    }

    initializeSubWindows();

    widget_->AddToViewport();

    //synchronize PIP views
    widget_->initializeForPlay();
    if (simmode_)
        widget_->setReportVisible(simmode_->EnableReport);
    widget_->setOnToggleRecordingHandler(std::bind(&ASimHUD::toggleRecordHandler, this));
    widget_->setRecordButtonVisibility(AirSimSettings::singleton().is_record_ui_visible);
    updateWidgetSubwindowVisibility();
}

void ASimHUD::setUnrealEngineSettings()
{
    //TODO: should we only do below on SceneCapture2D components and cameras?
    //avoid motion blur so capture images don't get
    //GetWorld()->GetGameViewport()->GetEngineShowFlags()->SetMotionBlur(false);

    //use two different methods to set console var because sometime it doesn't seem to work
    static const auto custom_depth_var = IConsoleManager::Get().FindConsoleVariable(TEXT("r.CustomDepth"));
    custom_depth_var->Set(3);

    //Equivalent to enabling Custom Stencil in Project > Settings > Rendering > Postprocessing
    UKismetSystemLibrary::ExecuteConsoleCommand(GetWorld(), FString("r.CustomDepth 3"));

    //during startup we init stencil IDs to random hash and it takes long time for large environments
    //we get error that GameThread has timed out after 30 sec waiting on render thread
    static const auto render_timeout_var = IConsoleManager::Get().FindConsoleVariable(TEXT("g.TimeoutForBlockOnRenderFence"));
    render_timeout_var->Set(300000);
}

void ASimHUD::setupInputBindings()
{
    UAirBlueprintLib::EnableInput(this);

    UAirBlueprintLib::BindActionToKey("inputEventToggleRecording", EKeys::R, this, &ASimHUD::inputEventToggleRecording);
    UAirBlueprintLib::BindActionToKey("InputEventToggleReport", EKeys::Semicolon, this, &ASimHUD::inputEventToggleReport);
    UAirBlueprintLib::BindActionToKey("InputEventToggleHelp", EKeys::F1, this, &ASimHUD::inputEventToggleHelp);
    UAirBlueprintLib::BindActionToKey("InputEventToggleTrace", EKeys::T, this, &ASimHUD::inputEventToggleTrace);

    UAirBlueprintLib::BindActionToKey("InputEventToggleSubwindow0", EKeys::One, this, &ASimHUD::inputEventToggleSubwindow0);
    UAirBlueprintLib::BindActionToKey("InputEventToggleSubwindow1", EKeys::Two, this, &ASimHUD::inputEventToggleSubwindow1);
    UAirBlueprintLib::BindActionToKey("InputEventToggleSubwindow2", EKeys::Three, this, &ASimHUD::inputEventToggleSubwindow2);
    UAirBlueprintLib::BindActionToKey(
    "InputEventToggleSubwindow3",
    EKeys::Four,
    this,
    &ASimHUD::inputEventToggleSubwindow3
);
    UAirBlueprintLib::BindActionToKey("InputEventToggleAll", EKeys::Zero, this, &ASimHUD::inputEventToggleAll);
}

void ASimHUD::initializeSettings()
{
    std::string settingsText;
    if (getSettingsText(settingsText))
        AirSimSettings::initializeSettings(settingsText);
    else
        AirSimSettings::createDefaultSettingsFile();

    AirSimSettings::singleton().load(std::bind(&ASimHUD::getSimModeFromUser, this));
    for (const auto& warning : AirSimSettings::singleton().warning_messages) {
        UAirBlueprintLib::LogMessageString(warning, "", LogDebugLevel::Failure);
    }
    for (const auto& error : AirSimSettings::singleton().error_messages) {
        UAirBlueprintLib::ShowMessage(EAppMsgType::Ok, error, "settings.json");
    }
}

const std::vector<ASimHUD::AirSimSettings::SubwindowSetting>& ASimHUD::getSubWindowSettings() const
{
    return AirSimSettings::singleton().subwindow_settings;
}

std::vector<ASimHUD::AirSimSettings::SubwindowSetting>& ASimHUD::getSubWindowSettings()
{
    return AirSimSettings::singleton().subwindow_settings;
}

std::string ASimHUD::getSimModeFromUser()
{
    if (EAppReturnType::No == UAirBlueprintLib::ShowMessage(EAppMsgType::YesNo,
                                                            "Would you like to use car/skid-vehicle simulation? Choose no to use quadrotor simulation.",
                                                            "Choose Vehicle")) {
        return AirSimSettings::kSimModeTypeMultirotor;
    }
    else
        if (EAppReturnType::No == UAirBlueprintLib::ShowMessage(EAppMsgType::YesNo,
                                                                "Would you like to use car simulation? Choose no to use skid-vehicle simulation.",
                                                                "Choose Vehicle")) {
            return AirSimSettings::kSimModeTypeSkidVehicle;
        }
        else
            return AirSimSettings::kSimModeTypeCar;
}

void ASimHUD::loadLevel()
{
    UAirBlueprintLib::RunCommandOnGameThread([&]() { this->map_changed_ = UAirBlueprintLib::loadLevel(this->GetWorld(), FString(AirSimSettings::singleton().level_name.c_str())); }, true);
}

void ASimHUD::createSimMode()
{
    std::string simmode_name = AirSimSettings::singleton().simmode_name;

    FActorSpawnParameters simmode_spawn_params;
    simmode_spawn_params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AdjustIfPossibleButAlwaysSpawn;

    //spawn at origin. We will use this to do global NED transforms, for ex, non-vehicle objects in environment
    if (simmode_name == AirSimSettings::kSimModeTypeMultirotor)
        simmode_ = this->GetWorld()->SpawnActor<ASimModeWorldMultiRotor>(FVector::ZeroVector,
                                                                         FRotator::ZeroRotator,
                                                                         simmode_spawn_params);
    else if (simmode_name == AirSimSettings::kSimModeTypeCar)
        simmode_ = this->GetWorld()->SpawnActor<ASimModeCar>(FVector::ZeroVector,
                                                             FRotator::ZeroRotator,
                                                             simmode_spawn_params);
    else if (simmode_name == AirSimSettings::kSimModeTypeSkidVehicle)
        simmode_ = this->GetWorld()->SpawnActor<ASimModeSkidVehicle>(FVector::ZeroVector,
                                                                     FRotator::ZeroRotator,
                                                                     simmode_spawn_params);
    else if (simmode_name == AirSimSettings::kSimModeTypeComputerVision)
        simmode_ = this->GetWorld()->SpawnActor<ASimModeComputerVision>(FVector::ZeroVector,
                                                                        FRotator::ZeroRotator,
                                                                        simmode_spawn_params);
    else {
        UAirBlueprintLib::ShowMessage(EAppMsgType::Ok, std::string("SimMode is not valid: ") + simmode_name, "Error");
        UAirBlueprintLib::LogMessageString("SimMode is not valid: ", simmode_name, LogDebugLevel::Failure);
    }
}

void ASimHUD::initializeSubWindows()
{
    if (!simmode_)
        return;

    // Always initialize every slot.
    for (int i = 0;
         i < AirSimSettings::kSubwindowCount;
         ++i)
    {
        subwindow_cameras_[i] = nullptr;
    }

    auto default_vehicle_sim_api =
        simmode_->getVehicleSimApi();

    if (default_vehicle_sim_api) {

        const auto camera_count =
            default_vehicle_sim_api->getCameraCount();

        if (camera_count > 0) {

            APIPCamera* default_camera =
                default_vehicle_sim_api->getCamera("");

            for (int i = 0;
                 i < AirSimSettings::kSubwindowCount;
                 ++i)
            {
                subwindow_cameras_[i] =
                    default_camera;
            }
        }
    }

    // Apply settings.json camera overrides.
    for (const auto& setting : getSubWindowSettings()) {

        APIPCamera* camera =
            simmode_->getCamera(
                msr::airlib::CameraDetails(
                    setting.camera_name,
                    setting.vehicle_name
                )
            );

        if (camera) {

            if (setting.window_index >= 0 &&
                setting.window_index <
                    AirSimSettings::kSubwindowCount)
            {
                subwindow_cameras_[setting.window_index] =
                    camera;
            }
        }
        else {
            UAirBlueprintLib::LogMessageString(
                "Invalid Camera settings in <SubWindows> element",
                std::to_string(setting.window_index),
                LogDebugLevel::Failure
            );
        }
    }
}

FString ASimHUD::getLaunchPath(const std::string& filename)
{
    FString launch_rel_path = FPaths::LaunchDir();
    FString abs_path = FPaths::ConvertRelativePathToFull(launch_rel_path);
    return FPaths::Combine(abs_path, FString(filename.c_str()));
}

// Attempts to parse the settings text from one of multiple locations.
// First, check the command line for settings provided via "-s" or "--settings" arguments
// Next, check the executable's working directory for the settings file.
// Finally, check the user's documents folder.
// If the settings file cannot be read, throw an exception

bool ASimHUD::getSettingsText(std::string& settingsText)
{
    return (getSettingsTextFromCommandLine(settingsText) ||
            readSettingsTextFromFile(FString(msr::airlib::Settings::getExecutableFullPath("settings.json").c_str()), settingsText) ||
            readSettingsTextFromFile(getLaunchPath("settings.json"), settingsText) ||
            readSettingsTextFromFile(FString(msr::airlib::Settings::Settings::getUserDirectoryFullPath("settings.json").c_str()), settingsText));
}

// Attempts to parse the settings file path or the settings text from the command line
// Looks for the flag "-settings=". If it exists, settingsText will be set to the value.
// Example (Path): AirSim.exe -settings="C:\path\to\settings.json"
// Example (Text): AirSim.exe -settings={"foo":"bar"} -> settingsText will be set to {"foo":"bar"}
// Returns true if the argument is present, false otherwise.
bool ASimHUD::getSettingsTextFromCommandLine(std::string& settingsText)
{
    const TCHAR* commandLineArgs = FCommandLine::Get();
    FString settingsJsonFString;

    if (FParse::Value(commandLineArgs, TEXT("-settings="), settingsJsonFString, false)) {
        if (readSettingsTextFromFile(settingsJsonFString, settingsText)) {
            return true;
        }
        else {
            UAirBlueprintLib::LogMessageString("Loaded settings from commandline: ", TCHAR_TO_UTF8(*settingsJsonFString), LogDebugLevel::Informational);
            settingsText = TCHAR_TO_UTF8(*settingsJsonFString);
            return true;
        }
    }

    return false;
}

bool ASimHUD::readSettingsTextFromFile(const FString& settingsFilepath, std::string& settingsText)
{
    bool found = FPaths::FileExists(settingsFilepath);
    if (found) {
        FString settingsTextFStr;
        bool readSuccessful = FFileHelper::LoadFileToString(settingsTextFStr, *settingsFilepath);
        if (readSuccessful) {
            UAirBlueprintLib::LogMessageString("Loaded settings from ", TCHAR_TO_UTF8(*settingsFilepath), LogDebugLevel::Informational);
            settingsText = TCHAR_TO_UTF8(*settingsTextFStr);
        }
        else {
            UAirBlueprintLib::LogMessageString("Cannot read file ", TCHAR_TO_UTF8(*settingsFilepath), LogDebugLevel::Failure);
            throw std::runtime_error("Cannot read settings file.");
        }
    }

    return found;
}

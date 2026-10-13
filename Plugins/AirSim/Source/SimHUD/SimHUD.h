#pragma once

#include "Engine/Texture2D.h"
#include <atomic>
#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "SimHUDWidget.h"
#include "SimMode/SimModeBase.h"
#include "PIPCamera.h"
#include "api/ApiServerBase.hpp"
#include <memory>
#include "ThermalGpuRenderer.h"
#include "ThermalGpuInputs.h"
#include "SimHUD.generated.h"

UENUM(BlueprintType)
enum class ESimulatorMode : uint8
{
    SIM_MODE_HIL UMETA(DisplayName = "Hardware-in-loop")
};

UCLASS()
class AIRSIM_API ASimHUD : public AHUD
{
    GENERATED_BODY()

public:
    typedef msr::airlib::ImageCaptureBase::ImageType ImageType;
    typedef msr::airlib::AirSimSettings AirSimSettings;

public:
    void inputEventToggleRecording();
    void inputEventToggleReport();
    void inputEventToggleHelp();
    void inputEventToggleTrace();
    void inputEventToggleSubwindow0();
    void inputEventToggleSubwindow1();
    void inputEventToggleSubwindow2();
    void inputEventToggleSubwindow3();
    void inputEventToggleAll();

    ASimHUD();
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
    virtual void Tick(float DeltaSeconds) override;
    UFUNCTION(BlueprintPure, Category="Thermal|Diagnostics")
    FString getThermalGpuStats() const;
    /** Diagnostic: render a fixed-size main viewport for reproducible profiling. */
    UFUNCTION(BlueprintCallable, Category="Thermal|Diagnostics")
    bool setThermalReviewViewportSize(int32 Width, int32 Height);
    UFUNCTION(BlueprintCallable, Category="Thermal|Diagnostics")
    bool saveThermalGpuPreview(const FString& Path);
    UFUNCTION(BlueprintCallable, Category="Thermal|Diagnostics")
    bool saveThermalCpuReference(const FString& Path);
    bool captureThermalGpuImage(APIPCamera* Camera, TArray<FColor>& Pixels, int32& Width, int32& Height);

protected:
    virtual void setupInputBindings();
    void toggleRecordHandler();
    void updateWidgetSubwindowVisibility();
    bool isWidgetSubwindowVisible(int window_index);
    void toggleSubwindowVisibility(int window_index);

private:
    void initializeSubWindows();
    void createSimMode();
    void initializeSettings();
    void setUnrealEngineSettings();
    void loadLevel();
    void createMainWidget();
    void requestThermalLiveFrame();
    bool requestThermalGpuFrame();
    bool prepareThermalGpuFrame(APIPCamera* Camera);
    bool finishThermalGpuFrame();
    void restoreThermalStencil();
    void updateThermalLiveTexture(
        int32 width,
        int32 height,
        std::vector<uint8_t>&& rgb_data
    );
    const std::vector<AirSimSettings::SubwindowSetting>& getSubWindowSettings() const;
    std::vector<AirSimSettings::SubwindowSetting>& getSubWindowSettings();

    bool getSettingsText(std::string& settingsText);
    bool getSettingsTextFromCommandLine(std::string& settingsText);
    bool readSettingsTextFromFile(const FString& fileName, std::string& settingsText);
    std::string getSimModeFromUser();

    static FString getLaunchPath(const std::string& filename);

private:
    typedef common_utils::Utils Utils;
    UClass* widget_class_;

    UPROPERTY()
    USimHUDWidget* widget_;
    UPROPERTY()
    ASimModeBase* simmode_;

    APIPCamera* subwindow_cameras_[AirSimSettings::kSubwindowCount];
    bool map_changed_;
    
    UPROPERTY()
    UTexture2D* thermal_live_texture_ = nullptr;
    UPROPERTY() UTextureRenderTarget2D* thermal_gpu_texture_ = nullptr;
    TWeakObjectPtr<UTexture> thermal_bound_texture_;
    TUniquePtr<FThermalGpuRenderer> thermal_gpu_renderer_;
    TUniquePtr<FThermalGpuInputs> thermal_gpu_inputs_;
    UPROPERTY() USceneCaptureComponent2D* thermal_geometry_capture_ = nullptr;
    UPROPERTY() UTextureRenderTarget2D* thermal_geometry_target_ = nullptr;
    UPROPERTY() UTextureRenderTarget2D* thermal_identity_target_ = nullptr;
    UPROPERTY() UTextureRenderTarget2D* thermal_camera_target_ = nullptr;
    TUniquePtr<FThermalGpuFrame> thermal_pending_frame_;
    FTransform thermal_pending_transform_;
    float thermal_pending_fov_ = 65;
    TSharedPtr<TArray<FThermalGpuProfile>, ESPMode::ThreadSafe> thermal_packed_profiles_;
    TMap<uint32, uint32> thermal_packed_ids_;
    uint64 thermal_packed_revision_ = 0;
    uint64 thermal_source_profile_revision_ = MAX_uint64;
    uint64 thermal_source_topology_revision_ = MAX_uint64;
    struct FStencilRestore {
        TWeakObjectPtr<UPrimitiveComponent> Component;
        bool Enabled;
        int32 Value;
        ERendererStencilMask Mask;
    };
    TArray<FStencilRestore> thermal_stencil_restore_;
    TSet<TWeakObjectPtr<UPrimitiveComponent>> thermal_stencil_seen_;
    FDelegateHandle thermal_gpu_end_draw_;
    TWeakObjectPtr<UGameViewportClient> thermal_gpu_viewport_;
    bool thermal_review_fixed_viewport_ = false;

    int32 thermal_live_width_ = 0;
    int32 thermal_live_height_ = 0;

    // GPU preview runs at 30 Hz; simulation and RPC captures are independent.
    float thermal_live_elapsed_ = 0.0f;
    float thermal_live_interval_ = 1.f / 30.f;
    float rgb_live_elapsed_ = 0;

    // Prevent two thermal readbacks from running simultaneously.
    std::atomic<bool> thermal_request_in_flight_{ false };
};

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

    int32 thermal_live_width_ = 0;
    int32 thermal_live_height_ = 0;

    // 10 FPS initially.
    float thermal_live_elapsed_ = 0.0f;
    float thermal_live_interval_ = 0.0167f;

    // Prevent two thermal readbacks from running simultaneously.
    std::atomic<bool> thermal_request_in_flight_{ false };
};

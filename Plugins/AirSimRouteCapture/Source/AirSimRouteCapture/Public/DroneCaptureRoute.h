#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "HAL/PlatformProcess.h"
#include "Containers/Ticker.h"
#include "DroneCaptureRoute.generated.h"

class UArrowComponent;
class UTextRenderComponent;
class USplineComponent;

UENUM(BlueprintType)
enum class ERouteNodeCapture : uint8 { Off, Single, Burst };
UENUM(BlueprintType)
enum class ERouteTravelCapture : uint8 { Off, TimeInterval, DistanceInterval };

USTRUCT(BlueprintType)
struct AIRSIMROUTECAPTURE_API FRouteNodeSettings
{
    GENERATED_BODY()
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Node") bool bFlyThrough = false;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Node", meta=(ClampMin="0.01")) float ArrivalRadiusM = .25f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Node", meta=(ClampMin="0.01")) float MaxSettledSpeedMps = .2f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Node", meta=(ClampMin="0.01", ClampMax="180")) float AimToleranceDeg = 1;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Node", meta=(ClampMin="0")) int32 SettleTimeMs = 500;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Node", meta=(ClampMin="0")) int32 ExtraHoldMs = 0;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Capture") ERouteNodeCapture Capture = ERouteNodeCapture::Single;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Capture", meta=(ClampMin="0")) int32 DelayMs = 0;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Capture", meta=(ClampMin="2", ClampMax="10000")) int32 BurstCount = 3;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Capture", meta=(ClampMin="1")) int32 BurstIntervalMs = 1000;
};

USTRUCT(BlueprintType)
struct AIRSIMROUTECAPTURE_API FRouteSegmentSettings
{
    GENERATED_BODY()
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Flight", meta=(ClampMin="0.01")) float SpeedMps = 2;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Flight", meta=(ClampMin="0.01")) float AccelerationMps2 = 1;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Flight", meta=(ClampMin="0.01")) float DecelerationMps2 = 1;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Flight", meta=(ClampMin="0.01")) float TimeoutS = 60;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Capture") ERouteTravelCapture Capture = ERouteTravelCapture::TimeInterval;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Capture", meta=(ClampMin="1")) int32 IntervalMs = 1000;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Capture", meta=(ClampMin="0.01")) float IntervalM = 1;
};

UCLASS(BlueprintType, Blueprintable)
class AIRSIMROUTECAPTURE_API ADroneRoutePoint : public AActor
{
    GENERATED_BODY()
public:
    ADroneRoutePoint();
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Route") FString PointId;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Route") FString PointLabel = TEXT("View");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Route") bool bEnabled = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Route") bool bOverrideSettings = false;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Route") FRouteNodeSettings Settings;
    /** Demo observer only. Always excluded from every drone camera and thermal geometry. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Preview") bool bDemoVisibleInGame = false;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Preview") int32 DisplayNumber = 0;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Preview") TObjectPtr<UArrowComponent> Direction;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Preview") TObjectPtr<UTextRenderComponent> Number;
    void UpdateNumber(int32 Value);
    virtual void OnConstruction(const FTransform& Transform) override;
    virtual void BeginPlay() override;
    virtual void PostDuplicate(EDuplicateMode::Type DuplicateMode) override;
};

USTRUCT(BlueprintType)
struct AIRSIMROUTECAPTURE_API FDroneRouteSegment
{
    GENERATED_BODY()
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Segment") FString SegmentId;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Segment") TObjectPtr<ADroneRoutePoint> From;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Segment") TObjectPtr<ADroneRoutePoint> To;
    /** False retains imported identity while inheriting the route defaults. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Segment") bool bOverrideSettings = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Segment", meta=(EditCondition="bOverrideSettings")) FRouteSegmentSettings Settings;
};

UCLASS(BlueprintType, Blueprintable)
class AIRSIMROUTECAPTURE_API ADroneCaptureRoute : public AActor
{
    GENERATED_BODY()
public:
    ADroneCaptureRoute();
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Route") FString RouteId;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Route") FString RouteName = TEXT("Inspection route");
    /** Authoritative order. Disabled points are excluded on export. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Route") TArray<TObjectPtr<ADroneRoutePoint>> OrderedPoints;
    /** Explicit endpoint references preserve overrides when order changes. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Route") TArray<FDroneRouteSegment> SegmentOverrides;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Connection") FString VehicleName;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Connection") FString CameraName = TEXT("0");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Connection") int32 RpcPort = 41451;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Defaults") FRouteNodeSettings DefaultNode;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Defaults") FRouteSegmentSettings DefaultSegment;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Capture") int32 WidthPx = 1280;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Capture") int32 HeightPx = 720;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Capture") float HorizontalFovDeg = 65;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal") int32 WarmupMs = 10000;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal") float ThermalMinK = 280;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal") float ThermalMaxK = 380;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Output") FString OutputRoot = TEXT("Saved/DroneCaptures");
    /** Preserves all advanced schema fields on import. Typed properties above override their corresponding fields on export. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Advanced", meta=(MultiLine=true)) FString MissionTemplateJson;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Worker") FString PythonExecutable = TEXT(".venv/Scripts/python.exe");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="JSON") FString JsonFile = TEXT("Saved/RouteMission.json");
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Transient, Category="Status") FString Status = TEXT("Ready");
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Transient, Category="Status") FString RunDirectory;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Preview") TObjectPtr<USplineComponent> Preview;
    UFUNCTION(BlueprintCallable, CallInEditor, Category="Route Capture") FString ValidateRoute();
    UFUNCTION(BlueprintCallable, CallInEditor, Category="Route Capture") bool ExportMission();
    UFUNCTION(BlueprintCallable, CallInEditor, Category="Route Capture") bool ImportMission();
    UFUNCTION(BlueprintCallable, Category="Route Capture") bool Start();
    UFUNCTION(BlueprintCallable, Category="Route Capture") void Pause();
    UFUNCTION(BlueprintCallable, Category="Route Capture") void Resume();
    UFUNCTION(BlueprintCallable, Category="Route Capture") void StopHover();
    UFUNCTION(BlueprintCallable, Category="Route Capture") void Land();
    UFUNCTION(BlueprintCallable, CallInEditor, Category="Route Capture") void OpenOutputFolder();
    UFUNCTION(BlueprintCallable, CallInEditor, Category="Route Capture") void RefreshPreview();
    bool IsWorkerRunning() const;
    virtual void OnConstruction(const FTransform& Transform) override;
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type Reason) override;
    virtual void PostDuplicate(EDuplicateMode::Type DuplicateMode) override;
private:
    TSharedPtr<class FJsonObject> MakeMission(FString& Error) const;
    bool WriteContext(const TSharedPtr<FJsonObject>& Mission, FString& Error);
    bool Supervise(float Delta);
    void SendControl(const FString& Command);
    bool LaunchRecovery(bool bLand = false);
    mutable FProcHandle Worker;
    FTSTicker::FDelegateHandle Ticker;
    FIntVector InitialWorldOrigin = FIntVector::ZeroValue;
    FString LastWorkerStatus;
    FString LastWorkerState;
    TArray<TWeakObjectPtr<AActor>> SnapshotMarkerActors;
    double LastStatusTime = 0, WorkerStartTime = 0;
    int64 CommandId = 0;
    bool bWatchdogSentStop = false;
    bool bRecoveryAttempted = false;
    bool bRecoveryLanding = false;
    double SnapshotClearanceM = .5;
};

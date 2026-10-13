#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "Components/ActorComponent.h"
#include "ThermalSource.generated.h"

UENUM(BlueprintType)
enum class EThermalSourceType : uint8 { Point, Spot, Rect, Directional, Capsule };

UENUM(BlueprintType)
enum class EThermalContactRegion : uint8 { Falloff, FiniteCylinder };

/** Optional material response override. Auto-discovered meshes work without it. */
UCLASS(ClassGroup=(Thermal), BlueprintType, meta=(BlueprintSpawnableComponent))
class AIRSIM_API UThermalReceiverComponent : public UActorComponent
{
    GENERATED_BODY()
public:
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="1")) float BaselineTemperatureKelvin = 295.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="0.01", ClampMax="1")) float Emissivity = .9f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="1")) float ArealHeatCapacity = 1500.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="0")) float CoolingCoefficient = 12.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="2")) float SampleSpacingCm = 8.0f;
};

/** IR-only energy emitter. +X is emission direction; capsule extends along Z.
 * Attach to an unchanged receiver mesh or use as a ChildActorComponent.
 * Has no light, mesh, collision or RGB material side effects. */
UCLASS(BlueprintType, Blueprintable)
class AIRSIM_API AThermalSource : public AActor
{
    GENERATED_BODY()
public:
    AThermalSource();
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal") EThermalSourceType SourceType = EThermalSourceType::Point;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal") bool Enabled = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="1")) float TemperatureKelvin = 450.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="0")) float PowerScale = 1.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="1")) float RangeCm = 300.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="1")) float RadiusCm = 25.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="0", ClampMax="89")) float InnerConeDegrees = 20.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="0", ClampMax="89")) float OuterConeDegrees = 40.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="1")) float RectWidthCm = 50.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="1")) float RectHeightCm = 50.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="0")) float CapsuleLengthCm = 100.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal") bool Occlusion = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal") bool HeatParentSurface = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="1")) float ParentContactRadiusCm = 45.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal", meta=(ClampMin="0")) float ParentConductance = 80.0f;
    // Contact region is independent of radiative source shape. Cylinder +X is
    // its axle, with uniform coverage over the selected annular volume.
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal|Parent Contact") EThermalContactRegion ParentContactRegion = EThermalContactRegion::Falloff;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal|Parent Contact", meta=(ClampMin="0", EditCondition="ParentContactRegion == EThermalContactRegion::FiniteCylinder")) float ParentContactInnerRadiusCm = 0.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal|Parent Contact", meta=(ClampMin="0", EditCondition="ParentContactRegion == EThermalContactRegion::FiniteCylinder")) float ParentContactOuterRadiusCm = 45.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal|Parent Contact", meta=(ClampMin="0", EditCondition="ParentContactRegion == EThermalContactRegion::FiniteCylinder")) float ParentContactHalfLengthCm = 10.0f;
    // Empty means all parent mesh material slots. Only direct parent contact is
    // filtered; normal physical radiation onto the parent/neighbours continues.
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal|Parent Contact") TArray<int32> ParentMaterialIndices;
    // Explicit receiver actor is useful for detached sources; otherwise attachment parent.
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal") TObjectPtr<AActor> ParentReceiver;
    UFUNCTION(BlueprintCallable, Category="Thermal") void SetSourceEnabled(bool bEnabled);
    UFUNCTION(BlueprintCallable, Category="Thermal") void ResetThermalState();
    UFUNCTION(BlueprintCallable, Category="Thermal") void Prewarm(float Seconds);
    UFUNCTION(BlueprintPure, Category="Thermal") float GetSurfaceTemperature(FVector WorldPoint) const;
    UFUNCTION(BlueprintPure, Category="Thermal") float GetSurfaceTemperatureWithNormal(FVector WorldPoint, FVector WorldNormal) const;
    UFUNCTION(BlueprintPure, Category="Thermal") int32 GetThermalSampleCount() const;
    AActor* GetReceiverActor() const;
    FVector GetEmitterPoint(const FVector& ReceiverPoint) const;
    double GetRadiationWeight(const FVector& ReceiverPoint, const FVector& Normal) const;
    double GetContactWeight(const FVector& ReceiverPoint) const;
    bool IsParentMaterialAllowed(int32 MaterialIndex) const;
    double GetDiscoveryRadius() const;
protected:
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
};

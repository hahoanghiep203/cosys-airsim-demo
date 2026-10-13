#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "ThermalSceneSettings.generated.h"

/** One editable scene baseline controller; explicit object settings take priority. */
UCLASS(BlueprintType, Blueprintable)
class AIRSIM_API AThermalSceneSettings : public AActor
{
    GENERATED_BODY()
public:
    AThermalSceneSettings();
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal Scene|Temperatures") float TreeTemperatureCelsius = 20;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal Scene|Temperatures") float BushTemperatureCelsius = 19;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal Scene|Temperatures") float GrassTemperatureCelsius = 18;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal Scene|Temperatures") float RoadTemperatureCelsius = 32;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal Scene|Temperatures") float ConcreteTemperatureCelsius = 28;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal Scene|Temperatures") float GroundTemperatureCelsius = 25;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal Scene|Temperatures") float WaterTemperatureCelsius = 20;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal Scene|Temperatures") float BuildingTemperatureCelsius = 24;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal Scene|Temperatures") float MetalTemperatureCelsius = 24;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal Scene|Temperatures") float WoodTemperatureCelsius = 22;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal Scene|Temperatures") float VehicleTemperatureCelsius = 25;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Thermal Scene|Temperatures") float DefaultTemperatureCelsius = 22;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Thermal Scene") int32 AssignedMeshComponents = 0;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Thermal Scene") int32 AssignedMeshInstances = 0;
    UFUNCTION(BlueprintCallable, CallInEditor, Category="Thermal Scene") void ApplySceneTemperatures();
protected:
    virtual void BeginPlay() override;
};

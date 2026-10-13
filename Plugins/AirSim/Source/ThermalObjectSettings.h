#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "ThermalSource.h"

// Lightweight whole-object settings. They do not require triangle samples or
// a heat source, and apply to all instances rendered by a mesh component.
namespace ThermalObjectSettings
{
struct FValues
{
    float TemperatureKelvin = 295;
    float Emissivity = .9f;
    bool HasTemperature = false;
    bool HasEmissivity = false;
};
inline bool ReadTag(const TArray<FName>& Tags, const TCHAR* Key, float& Value)
{
    const FString Prefix = FString(Key) + TEXT("=");
    for (const FName& Tag : Tags) {
        const FString Text = Tag.ToString();
        float Parsed = 0;
        if (Text.StartsWith(Prefix, ESearchCase::IgnoreCase) &&
            LexTryParseString(Parsed, *Text.Mid(Prefix.Len())) && FMath::IsFinite(Parsed)) {
            Value = Parsed;
            return true;
        }
    }
    return false;
}
inline FValues ResolveWithResponse(const UActorComponent* Component, const UThermalReceiverComponent* Response,
                                  float DefaultTemperature = 295, float DefaultEmissivity = .9f)
{
    FValues Result;
    Result.TemperatureKelvin = DefaultTemperature;
    Result.Emissivity = DefaultEmissivity;
    const AActor* Owner = Component ? Component->GetOwner() : nullptr;
    const auto Apply = [&Result](const TArray<FName>& Tags, const TCHAR* TemperatureKey, const TCHAR* EmissivityKey) {
        Result.HasTemperature |= ReadTag(Tags, TemperatureKey, Result.TemperatureKelvin);
        Result.HasEmissivity |= ReadTag(Tags, EmissivityKey, Result.Emissivity);
    };
    // Scene-assigned baselines are the fallback. Explicit user tags override
    // them; the editable response component is the highest-priority setting.
    if (Owner) Apply(Owner->Tags, TEXT("ThermalBaselineK"), TEXT("ThermalBaselineEmissivity"));
    if (Component) Apply(Component->ComponentTags, TEXT("ThermalBaselineK"), TEXT("ThermalBaselineEmissivity"));
    if (Owner) Apply(Owner->Tags, TEXT("ThermalTempK"), TEXT("ThermalEmissivity"));
    if (Component) Apply(Component->ComponentTags, TEXT("ThermalTempK"), TEXT("ThermalEmissivity"));
    if (Response) {
        Result.TemperatureKelvin = Response->BaselineTemperatureKelvin;
        Result.Emissivity = Response->Emissivity;
        Result.HasTemperature = Result.HasEmissivity = true;
    }
    Result.TemperatureKelvin = FMath::Clamp(Result.TemperatureKelvin, 1.f, 1999.f);
    Result.Emissivity = FMath::Clamp(Result.Emissivity, .01f, 1.f);
    return Result;
}
inline FValues Resolve(const UActorComponent* Component, float DefaultTemperature = 295, float DefaultEmissivity = .9f)
{
    const AActor* Owner = Component ? Component->GetOwner() : nullptr;
    return ResolveWithResponse(Component, Owner ? Owner->FindComponentByClass<UThermalReceiverComponent>() : nullptr,
        DefaultTemperature, DefaultEmissivity);
}
}

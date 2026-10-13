#pragma once

#include "CoreMinimal.h"

// Units: cm for geometry; K, W/m2 and J/(m2 K) for thermal quantities.
namespace ThermalMath
{
inline double FourthPower(double Value) { const double Squared = Value * Value; return Squared * Squared; }
constexpr double StefanBoltzmann = 5.670374419e-8;
inline double Radiation(double SourceK, double SurfaceK)
{
    return StefanBoltzmann * (FMath::Pow(SourceK, 4.0) - FMath::Pow(SurfaceK, 4.0));
}
inline double DistanceWeight(double DistanceCm, double RadiusCm, double RangeCm)
{
    if (DistanceCm >= RangeCm || RangeCm <= 0.0) return 0.0;
    const double R = FMath::Max(1.0, RadiusCm);
    const double Edge = 1.0 - FMath::Square(DistanceCm / RangeCm);
    return FMath::Square(Edge) * R * R / (R * R + DistanceCm * DistanceCm);
}
inline double ConeWeight(double CosAngle, double InnerDegrees, double OuterDegrees)
{
    const double Inner = FMath::Cos(FMath::DegreesToRadians(InnerDegrees));
    const double Outer = FMath::Cos(FMath::DegreesToRadians(OuterDegrees));
    const double T = FMath::Clamp((CosAngle - Outer) / FMath::Max(1.e-6, Inner - Outer), 0.0, 1.0);
    return T * T * (3.0 - 2.0 * T);
}
// Backward Euler for convective loss prevents large steps overshooting ambient.
// Fluxes from every source are summed before this integration.
inline double Integrate(double TemperatureK, double AmbientK, double TotalFlux,
                        double Capacity, double Cooling, double Seconds)
{
    const double C = FMath::Max(1.0, Capacity);
    return FMath::Clamp((TemperatureK + Seconds * (TotalFlux + Cooling * AmbientK) / C)
        / (1.0 + Seconds * Cooling / C), 1.0, 2000.0);
}
// Monotone backward-Euler solve including every source's contact and nonlinear
// radiation exchange. Stable even for very low capacity or overlapping sources.
inline double IntegrateTransfers(double Current, double Ambient, double ContactInput,
    double ContactConductance, double RadiativeInput, double RadiativeCoefficient,
    double Capacity, double Cooling, double Seconds)
{
    if (Seconds <= 0) return Current;
    const double Rate = FMath::Max(1.0, Capacity) / Seconds;
    const auto Residual = [&](double T) {
        return Rate * (T - Current) + Cooling * (T - Ambient) + ContactConductance * T
            + RadiativeCoefficient * FourthPower(T) - ContactInput - RadiativeInput;
    };
    double Low = 1, High = 2000, T = FMath::Clamp(Current, Low, High);
    if (Residual(Low) >= 0) return Low;
    if (Residual(High) <= 0) return High;
    for (int Iteration = 0; Iteration < 20; ++Iteration) {
        const double F = Residual(T);
        if (FMath::Abs(F) < .000001) break;
        if (F > 0) High = T; else Low = T;
        const double Derivative = Rate + Cooling + ContactConductance + 4 * RadiativeCoefficient * T * T * T;
        const double Next = T - F / Derivative;
        T = Next > Low && Next < High ? Next : (Low + High) * .5;
    }
    return T;
}
inline FVector PlanarPixelWorld(const FTransform& Camera, double HorizontalTanHalfFov,
                               int32 X, int32 Y, int32 Width, int32 Height, double DepthMeters)
{
    // UE cameras look +X; +Y is right and +Z is up. DepthPlanar is forward
    // distance, not range. Read the UE capture transform directly, avoiding
    // mixing AirSim's NED response pose with the UE world origin/centimetres.
    const double Forward = DepthMeters * 100.0;
    const double Right = ((X + .5) * 2.0 / Width - 1.0) * HorizontalTanHalfFov * Forward;
    const double Up = (1.0 - (Y + .5) * 2.0 / Height) * HorizontalTanHalfFov * Height / Width * Forward;
    return Camera.TransformPosition(FVector(Forward, Right, Up));
}
}

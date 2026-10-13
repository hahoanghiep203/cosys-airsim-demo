#include "ThermalSource.h"
#include "ThermalWorldSubsystem.h"
#include "ThermalMath.h"
#include "Components/SceneComponent.h"
#include "Engine/World.h"

AThermalSource::AThermalSource()
{
    RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("ThermalOrigin"));
    PrimaryActorTick.bCanEverTick = false;
}
void AThermalSource::BeginPlay()
{
    Super::BeginPlay();
    GetWorld()->GetSubsystem<UThermalWorldSubsystem>()->RegisterSource(this);
}
void AThermalSource::EndPlay(const EEndPlayReason::Type Reason)
{
    if (auto* System = GetWorld()->GetSubsystem<UThermalWorldSubsystem>()) System->UnregisterSource(this);
    Super::EndPlay(Reason);
}
AActor* AThermalSource::GetReceiverActor() const
{
    if (ParentReceiver) return ParentReceiver;
    return GetAttachParentActor() ? GetAttachParentActor() : GetParentActor();
}
FVector AThermalSource::GetEmitterPoint(const FVector& ReceiverPoint) const
{
    const FTransform Transform = GetActorTransform();
    FVector Local = Transform.InverseTransformPosition(ReceiverPoint);
    if (SourceType == EThermalSourceType::Rect) {
        Local.X = 0;
        Local.Y = FMath::Clamp(Local.Y, -RectWidthCm * .5, RectWidthCm * .5);
        Local.Z = FMath::Clamp(Local.Z, -RectHeightCm * .5, RectHeightCm * .5);
    }
    else if (SourceType == EThermalSourceType::Capsule) {
        Local.X = Local.Y = 0;
        Local.Z = FMath::Clamp(Local.Z, -CapsuleLengthCm * .5, CapsuleLengthCm * .5);
    }
    else return GetActorLocation();
    return Transform.TransformPosition(Local);
}
double AThermalSource::GetRadiationWeight(const FVector& Point, const FVector& Normal) const
{
    const FVector Delta = Point - GetEmitterPoint(Point);
    const double Distance = Delta.Size();
    const FVector Direction = Delta.GetSafeNormal();
    const double Incidence = FMath::Max(0.0, FVector::DotProduct(Normal, -Direction));
    if (SourceType == EThermalSourceType::Directional) {
        // Finite disk/beam, no inverse-square loss inside the beam. Range is
        // measured along +X; RadiusCm sets beam width for bounded discovery.
        const FVector Local = GetActorTransform().InverseTransformPosition(Point);
        if (Local.X < 0 || Local.X >= RangeCm) return 0;
        const double R = FMath::Sqrt(Local.Y * Local.Y + Local.Z * Local.Z);
        const double Edge = FMath::Clamp(1.0 - R / FMath::Max(1.0f, RadiusCm), 0.0, 1.0);
        return Edge * Edge * FMath::Max(0.0, FVector::DotProduct(Normal, -GetActorForwardVector()));
    }
    double Weight = ThermalMath::DistanceWeight(Distance, RadiusCm, RangeCm) * Incidence;
    if (SourceType == EThermalSourceType::Spot)
        Weight *= ThermalMath::ConeWeight(FVector::DotProduct(Direction, GetActorForwardVector()), InnerConeDegrees, OuterConeDegrees);
    if (SourceType == EThermalSourceType::Rect)
        Weight *= FMath::Max(0.0, FVector::DotProduct(Direction, GetActorForwardVector()));
    return Weight;
}
double AThermalSource::GetContactWeight(const FVector& Point) const
{
    // Contact heating penetrates the local parent shell and therefore does not
    // use radiative facing or occlusion; it is spatially bounded and separate.
    if (ParentContactRegion == EThermalContactRegion::FiniteCylinder) {
        const FVector Local = GetActorTransform().InverseTransformPosition(Point);
        const double Inner = FMath::Max(0.0f, ParentContactInnerRadiusCm);
        const double Outer = FMath::Max(0.0f, ParentContactOuterRadiusCm);
        const double RadialSquared = Local.Y * Local.Y + Local.Z * Local.Z;
        if (Outer < Inner || FMath::Abs(Local.X) > FMath::Max(0.0f, ParentContactHalfLengthCm)) return 0;
        return RadialSquared >= Inner * Inner && RadialSquared <= Outer * Outer ? 1.0 : 0.0;
    }
    const double T = FMath::Clamp(1.0 - FVector::Distance(Point, GetEmitterPoint(Point)) / FMath::Max(1.0f, ParentContactRadiusCm), 0.0, 1.0);
    return T * T * (3.0 - 2.0 * T);
}
bool AThermalSource::IsParentMaterialAllowed(int32 MaterialIndex) const
{
    return ParentMaterialIndices.IsEmpty() || ParentMaterialIndices.Contains(MaterialIndex);
}
double AThermalSource::GetDiscoveryRadius() const
{
    double Radius = RangeCm;
    if (SourceType == EThermalSourceType::Directional) Radius = FMath::Sqrt(FMath::Square(double(RangeCm)) + FMath::Square(double(RadiusCm)));
    else if (SourceType == EThermalSourceType::Rect) Radius += .5 * FMath::Sqrt(FMath::Square(double(RectWidthCm)) + FMath::Square(double(RectHeightCm)));
    else if (SourceType == EThermalSourceType::Capsule) Radius += CapsuleLengthCm * .5;
    const double ContactRadius = ParentContactRegion == EThermalContactRegion::FiniteCylinder
        ? FMath::Sqrt(FMath::Square(double(FMath::Max(0.0f, ParentContactOuterRadiusCm))) + FMath::Square(double(FMath::Max(0.0f, ParentContactHalfLengthCm))))
        : double(ParentContactRadiusCm);
    return FMath::Max(Radius, ContactRadius);
}
void AThermalSource::SetSourceEnabled(bool bEnabled) { Enabled = bEnabled; }
void AThermalSource::ResetThermalState() { GetWorld()->GetSubsystem<UThermalWorldSubsystem>()->ResetThermalState(); }
void AThermalSource::Prewarm(float Seconds) { GetWorld()->GetSubsystem<UThermalWorldSubsystem>()->Prewarm(Seconds); }
float AThermalSource::GetSurfaceTemperature(FVector Point) const { return GetWorld()->GetSubsystem<UThermalWorldSubsystem>()->GetSurfaceTemperature(Point); }
float AThermalSource::GetSurfaceTemperatureWithNormal(FVector Point, FVector Normal) const { return GetWorld()->GetSubsystem<UThermalWorldSubsystem>()->GetSurfaceTemperature(Point, Normal.GetSafeNormal()); }
int32 AThermalSource::GetThermalSampleCount() const { return GetWorld()->GetSubsystem<UThermalWorldSubsystem>()->GetSampleCount(); }

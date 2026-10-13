#include "ThermalWorldSubsystem.h"
#include "ThermalSource.h"
#include "ThermalMath.h"
#include "Components/StaticMeshComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/SplineMeshComponent.h"
#include "ThermalObjectSettings.h"
#include "SimMode/SimModeBase.h"
#include "Engine/StaticMesh.h"
#include "StaticMeshResources.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Materials/MaterialInterface.h"
#include "UObject/UObjectIterator.h"
#include <limits>

namespace
{
FIntVector Cell(const FVector& P, double Spacing)
{
    return FIntVector(FMath::FloorToInt(P.X / Spacing), FMath::FloorToInt(P.Y / Spacing), FMath::FloorToInt(P.Z / Spacing));
}
FVector SurfaceNormal(const FTransform& T, const FVector& N)
{
    const FVector Scale = T.GetScale3D();
    const auto SafeScale = [](double Value) { return FMath::Abs(Value) > KINDA_SMALL_NUMBER ? Value : 1.0; };
    return T.TransformVectorNoScale(FVector(N.X / SafeScale(Scale.X), N.Y / SafeScale(Scale.Y), N.Z / SafeScale(Scale.Z))).GetSafeNormal();
}
FTransform ReceiverTransform(const FThermalReceiverState& R)
{
    const auto* C = R.Component.Get();
    if (!C) return FTransform::Identity;
    if (const auto* Instances = Cast<UInstancedStaticMeshComponent>(C)) {
        FTransform Transform;
        if (Instances->GetInstanceTransform(R.InstanceIndex, Transform, true)) return Transform;
    }
    return C->GetComponentTransform();
}
}

bool FThermalFrameSnapshot::Sample(const FVector& Point, float& Temperature, float& Emissivity, const FVector& WorldNormal,
                                 const TArray<int32>* CandidateReceivers) const
{
    double Best = TNumericLimits<double>::Max();
    const FThermalSnapshotReceiver* BestReceiver = nullptr;
    const FThermalSurfaceSample* BestSample = nullptr;
    const int32 CandidateCount = CandidateReceivers ? CandidateReceivers->Num() : Receivers.Num();
    for (int32 Index = 0; Index < CandidateCount; ++Index) {
        const auto& R = Receivers[CandidateReceivers ? (*CandidateReceivers)[Index] : Index];
        if (!R.WorldBounds.ExpandBy(R.SpacingCm * 2).IsInsideOrOn(Point)) continue;
        const FVector Local = R.Transform.InverseTransformPosition(Point);
        const FIntVector Key = Cell(Local, R.SpacingCm);
        for (int X = -1; X <= 1; ++X) for (int Y = -1; Y <= 1; ++Y) for (int Z = -1; Z <= 1; ++Z) {
            const auto* Bucket = R.Samples.Find(Key + FIntVector(X, Y, Z));
            if (!Bucket) continue;
            for (const auto& S : *Bucket) {
            if (!WorldNormal.IsNearlyZero() && FVector::DotProduct(SurfaceNormal(R.Transform, S.LocalNormal), WorldNormal) < .35) continue;
            const double LocalDistance = FVector::DistSquared(S.LocalPosition, Local);
            const double D = FVector::DistSquared(R.Transform.TransformPosition(S.LocalPosition), Point);
            // A depth surface must actually lie near this mesh sample. This
            // prevents hot empty volumes from painting unrelated silhouettes.
            const double PlaneDistance = FMath::Abs(FVector::DotProduct(Local - S.LocalPosition, S.LocalNormal));
            if (D < Best && LocalDistance < FMath::Square(R.SpacingCm * 1.75) && PlaneDistance < R.SpacingCm * .65) {
                Best = D; BestReceiver = &R; BestSample = &S;
            }
            }
        }
    }
    if (!BestSample) return false;
    Temperature = BestSample->TemperatureKelvin;
    Emissivity = BestSample->Emissivity;
    if (Best < 1.e-10) return true;

    // Reconstruct the stored surface field between samples. Restrict blending
    // to the selected receiver, material, orientation and local plane so hot
    // hood samples cannot bleed through a thin shell or onto the glass/trim.
    const auto& R = *BestReceiver;
    const FVector Local = R.Transform.InverseTransformPosition(Point);
    const FIntVector Key = Cell(Local, R.SpacingCm);
    const double Radius = R.SpacingCm * 1.5;
    double WeightedTemperature = 0, TotalWeight = 0;
    for (int X = -1; X <= 1; ++X) for (int Y = -1; Y <= 1; ++Y) for (int Z = -1; Z <= 1; ++Z) {
        const auto* Bucket = R.Samples.Find(Key + FIntVector(X, Y, Z));
        if (!Bucket) continue;
        for (const auto& S : *Bucket) {
            if (S.MaterialIndex != BestSample->MaterialIndex || FVector::DotProduct(S.LocalNormal, BestSample->LocalNormal) < .8) continue;
            if (FMath::Abs(FVector::DotProduct(S.LocalPosition - BestSample->LocalPosition, BestSample->LocalNormal)) > .2) continue;
            const double DistanceSquared = FVector::DistSquared(S.LocalPosition, Local);
            if (DistanceSquared >= Radius * Radius) continue;
            const double Edge = 1.0 - FMath::Sqrt(DistanceSquared) / Radius;
            const double Weight = Edge * Edge / FMath::Max(.001, DistanceSquared);
            WeightedTemperature += S.TemperatureKelvin * Weight;
            TotalWeight += Weight;
        }
    }
    if (TotalWeight > 0) Temperature = WeightedTemperature / TotalWeight;
    return true;
}
void FThermalFrameSnapshot::ResolvePixels(const std::vector<float>& Depth, int32 Width, int32 Height,
                                        std::vector<float>& Temperature, std::vector<float>& Emissivity,
                                        const std::vector<uint8_t>& NormalsRgb,
                                        const std::vector<uint8_t>& SegmentationRgb) const
{
    Temperature.clear(); Emissivity.clear();
    const size_t Count = static_cast<size_t>(Width) * Height;
    if (!Perspective || Width <= 0 || Height <= 0 || Depth.size() != Count) return;
    Temperature.assign(Count, std::numeric_limits<float>::quiet_NaN());
    Emissivity.assign(Count, .9f);
    if (Receivers.IsEmpty() && UniformUnannotatedSurfaces.IsEmpty()) return;
    for (size_t I = 0; I < Count; ++I) {
        if (!FMath::IsFinite(Depth[I]) || Depth[I] <= 0 || Depth[I] > 1.e5f) continue;
        const FVector Point = ThermalMath::PlanarPixelWorld(CameraTransform, TanHalfHorizontalFov,
            I % Width, I / Width, Width, Height, Depth[I]);
        FVector Normal = FVector::ZeroVector;
        if (NormalsRgb.size() == Count * 3)
            Normal = FVector(NormalsRgb[I * 3] / 127.5 - 1, NormalsRgb[I * 3 + 1] / 127.5 - 1, NormalsRgb[I * 3 + 2] / 127.5 - 1).GetSafeNormal();
        const TArray<int32>* Candidates = nullptr;
        const bool HasColor = SegmentationRgb.size() == Count * 3;
        if (HasSegmentationReceiverMap && HasColor)
            Candidates = ReceiversByColor.Find((uint32(SegmentationRgb[I*3]) << 16) | (uint32(SegmentationRgb[I*3+1]) << 8) | SegmentationRgb[I*3+2]);
        // Most pixels have no simulated receiver. Annotation identity lets us
        // skip their surface search and avoids testing every receiver per pixel.
        if ((!HasSegmentationReceiverMap || !HasColor || Candidates) && Sample(Point, Temperature[I], Emissivity[I], Normal, Candidates)) continue;
        // Landscapes are absent from Cosys' mesh-only instance annotation map.
        // A tagged terrain bounds fallback affects only unannotated depth
        // pixels, so trees, roads and props retain their own object profiles.
        if (SegmentationRgb.size() == Count * 3 &&
            (SegmentationRgb[I * 3] || SegmentationRgb[I * 3 + 1] || SegmentationRgb[I * 3 + 2])) continue;
        if (SegmentationRgb.size() != Count * 3) continue;
        for (const auto& Surface : UniformUnannotatedSurfaces) {
            if (!Surface.WorldBounds.IsInsideOrOn(Point)) continue;
            Temperature[I] = Surface.TemperatureKelvin;
            Emissivity[I] = Surface.Emissivity;
            break;
        }
    }
}

bool UThermalWorldSubsystem::DoesSupportWorldType(EWorldType::Type Type) const
{
    return Type == EWorldType::Game || Type == EWorldType::PIE || Type == EWorldType::Editor;
}
TStatId UThermalWorldSubsystem::GetStatId() const { RETURN_QUICK_DECLARE_CYCLE_STAT(UThermalWorldSubsystem, STATGROUP_Tickables); }
bool UThermalWorldSubsystem::IsTickable() const { return GetWorld() && GetWorld()->IsGameWorld(); }
void UThermalWorldSubsystem::RegisterSource(AThermalSource* Source)
{
    check(IsInGameThread());
    Sources.AddUnique(Source);
    DiscoveryTimer = 0;
}
void UThermalWorldSubsystem::UnregisterSource(AThermalSource* Source) { Sources.Remove(Source); }
void UThermalWorldSubsystem::Tick(float DeltaTime)
{
    check(IsInGameThread());
    DiscoveryTimer -= DeltaTime;
    if (DiscoveryTimer <= 0) { DiscoverReceivers(); DiscoveryTimer = 1.0f; }
    RefreshTransfers(.002);
    if (Receivers.IsEmpty()) return;
    // Simulated elapsed world time, independent of capture calls and visibility.
    AccumulatedTime += FMath::Max(0.0f, DeltaTime);
    // The implicit heat solver accepts a long step. Consume elapsed time once
    // after a hitch instead of creating an unbounded catch-up workload.
    if (AccumulatedTime >= .1f) { Advance(AccumulatedTime); AccumulatedTime = 0; }
}
void UThermalWorldSubsystem::DiscoverReceivers(bool ImmediateTransfers)
{
    for (TActorIterator<AThermalSource> It(GetWorld()); It; ++It) Sources.AddUnique(*It);
    Sources.RemoveAll([](const auto& S) { return !S.IsValid(); });
    const int32 Removed = Receivers.RemoveAll([](const auto& R) {
        if (!R.Component.IsValid()) return true;
        if (R.Component->ComponentHasTag(TEXT("ThermalIgnore")) || R.Component->GetOwner()->ActorHasTag(TEXT("ThermalIgnore"))) return true;
        const auto* Instances = Cast<UInstancedStaticMeshComponent>(R.Component.Get());
        return Instances && (R.InstanceIndex < 0 || R.InstanceIndex >= Instances->GetInstanceCount());
    });
    if (Removed) {
        ++GpuTopologyRevision;
        TransferRefreshPending = false;
        TransferReceiverIndex = TransferBucketIndex = 0;
        TransferBucketKeys.Reset();
    }
    if (Sources.IsEmpty()) return;
    for (TObjectIterator<UStaticMeshComponent> It; It; ++It) {
        UStaticMeshComponent* C = *It;
        if (C->GetWorld() != GetWorld() || !C->IsRegistered() || !C->GetStaticMesh() || !C->IsVisible()) continue;
        if (C->ComponentHasTag(TEXT("ThermalIgnore")) || C->GetOwner()->ActorHasTag(TEXT("ThermalIgnore"))) continue;
        bool Relevant = false;
        for (const auto& Weak : Sources) {
            const auto* S = Weak.Get();
            if (S->GetReceiverActor() == C->GetOwner() ||
                C->Bounds.GetBox().ComputeSquaredDistanceToPoint(S->GetActorLocation()) < FMath::Square(S->GetDiscoveryRadius())) {
                Relevant = true; break;
            }
        }
        if (!Relevant) continue;
        if (auto* Instances = Cast<UInstancedStaticMeshComponent>(C)) {
            TSet<int32> Nearby;
            for (const auto& Weak : Sources) if (const auto* S = Weak.Get())
                for (int32 Index : Instances->GetInstancesOverlappingSphere(S->GetActorLocation(), S->GetDiscoveryRadius(), true)) Nearby.Add(Index);
            for (int32 Index : Nearby) AddReceiver(C, Index);
        }
        else AddReceiver(C);
    }
    if (!TransferRefreshPending || ImmediateTransfers) {
        TransferRefreshPending = true;
        TransferReceiverIndex = TransferBucketIndex = 0;
        TransferBucketKeys.Reset();
    }
    if (ImmediateTransfers) RefreshTransfers();
}
void UThermalWorldSubsystem::AddReceiver(UStaticMeshComponent* C, int32 InstanceIndex)
{
    for (const auto& R : Receivers) if (R.Component == C && R.InstanceIndex == InstanceIndex) return;
    const auto* Data = C->GetStaticMesh()->GetRenderData();
    if (!Data || Data->LODResources.IsEmpty()) return;
    const auto& LOD = Data->LODResources[0];
    if (!LOD.VertexBuffers.PositionVertexBuffer.GetVertexData() || LOD.IndexBuffer.GetNumIndices() == 0) {
        // Cooked assets must retain CPU triangle data for persistent surface
        // simulation. Never substitute an invisible bounding-box heat surface.
        UE_LOG(LogTemp, Warning, TEXT("Thermal receiver %s needs Allow CPU Access on its static mesh"), *C->GetPathName());
        return;
    }
    FThermalReceiverState R;
    R.Component = C;
    R.InstanceIndex = InstanceIndex;
    const auto* Response = C->GetOwner()->FindComponentByClass<UThermalReceiverComponent>();
    if (Response) { R.SpacingCm = FMath::Max(2.0f, Response->SampleSpacingCm); R.BaselineKelvin = Response->BaselineTemperatureKelvin; }
    const auto ObjectValues = ThermalObjectSettings::Resolve(C, R.BaselineKelvin);
    R.BaselineKelvin = ObjectValues.TemperatureKelvin;
    // Spacing is world-sized, stored in local coordinates, and follows attached
    // and moving components. Limit oversized environment receivers sensibly.
    const double Scale = FMath::Max(.01, ReceiverTransform(R).GetScale3D().GetAbsMax());
    R.SpacingCm /= Scale;
    const double Size = Cast<USplineMeshComponent>(C)
        ? C->CalcBounds(FTransform::Identity).BoxExtent.GetMax() * 2.0
        : C->GetStaticMesh()->GetBoundingBox().GetSize().GetMax();
    R.SpacingCm = FMath::Max(R.SpacingCm, static_cast<float>(Size / 128.0));
    const auto* Spline = Cast<USplineMeshComponent>(C);
    const auto Deform = [Spline](FVector Point) {
        if (!Spline) return Point;
        const int32 Axis = static_cast<int32>(Spline->GetForwardAxis());
        const FTransform Slice = Spline->CalcSliceTransform(Point[Axis]);
        Point[Axis] = 0;
        return Slice.TransformPosition(Point);
    };
    for (int32 SectionIndex = 0; SectionIndex < LOD.Sections.Num(); ++SectionIndex) {
        const auto& Section = LOD.Sections[SectionIndex];
        FThermalSurfaceSample Material;
        Material.MaterialIndex = Section.MaterialIndex;
        Material.TemperatureKelvin = R.BaselineKelvin;
        if (Response) { Material.Emissivity = FMath::Clamp(Response->Emissivity, .01f, 1.f); Material.Capacity = Response->ArealHeatCapacity; Material.Cooling = Response->CoolingCoefficient; }
        else {
            const auto* M = C->GetMaterial(Section.MaterialIndex);
            const FString Name = M ? M->GetName().ToLower() : FString();
            if (Name.Contains(TEXT("rubber")) || Name.Contains(TEXT("tire"))) { Material.Emissivity = .96f; Material.Capacity = 2200; }
            else if (Name.Contains(TEXT("glass"))) { Material.Emissivity = .90f; Material.Capacity = 3000; }
            else if (Name.Contains(TEXT("chrome")) || Name.Contains(TEXT("metal"))) { Material.Emissivity = .35f; Material.Capacity = 1800; }
        }
        if (ObjectValues.HasEmissivity) Material.Emissivity = ObjectValues.Emissivity;
        for (uint32 Tri = 0; Tri < Section.NumTriangles; ++Tri) {
            const uint32 Index = Section.FirstIndex + Tri * 3;
            const FVector RawA(LOD.VertexBuffers.PositionVertexBuffer.VertexPosition(LOD.IndexBuffer.GetIndex(Index)));
            const FVector A = Deform(RawA);
            const FVector B = Deform(FVector(LOD.VertexBuffers.PositionVertexBuffer.VertexPosition(LOD.IndexBuffer.GetIndex(Index + 1))));
            const FVector D = Deform(FVector(LOD.VertexBuffers.PositionVertexBuffer.VertexPosition(LOD.IndexBuffer.GetIndex(Index + 2))));
            Material.LocalNormal = FVector::CrossProduct(B - A, D - A).GetSafeNormal();
            if (LOD.VertexBuffers.StaticMeshVertexBuffer.GetTangentData()) {
                const FVector4f Tangent = LOD.VertexBuffers.StaticMeshVertexBuffer.VertexTangentZ(LOD.IndexBuffer.GetIndex(Index));
                FVector AuthoredNormal(Tangent.X, Tangent.Y, Tangent.Z);
                if (Spline) AuthoredNormal = SurfaceNormal(Spline->CalcSliceTransform(RawA[static_cast<int32>(Spline->GetForwardAxis())]), AuthoredNormal);
                if (FVector::DotProduct(Material.LocalNormal, AuthoredNormal) < 0) Material.LocalNormal *= -1;
            }
            if (Material.LocalNormal.IsNearlyZero()) continue;
            const double Longest = FMath::Max3(FVector::Distance(A, B), FVector::Distance(A, D), FVector::Distance(B, D));
            const int32 Steps = FMath::Clamp(FMath::CeilToInt(Longest / (R.SpacingCm * .7)), 1, 256);
            for (int32 U = 0; U <= Steps; ++U) for (int32 V = 0; V <= Steps - U; ++V) {
                Material.LocalPosition = A + (B - A) * (double(U) / Steps) + (D - A) * (double(V) / Steps);
                const FIntVector Key = Cell(Material.LocalPosition, R.SpacingCm);
                auto& Bucket = R.Samples.FindOrAdd(Key);
                // Keep separate opposing faces, material boundaries and parallel
                // thin shells inside one voxel. Only merge the same local plane.
                const bool AlreadySampled = Bucket.ContainsByPredicate([&Material](const auto& Existing) {
                    return Existing.MaterialIndex == Material.MaterialIndex &&
                        FVector::DotProduct(Existing.LocalNormal, Material.LocalNormal) > .98 &&
                        FMath::Abs(FVector::DotProduct(Material.LocalPosition - Existing.LocalPosition, Existing.LocalNormal)) < .1;
                });
                if (!AlreadySampled) Bucket.Add(Material);
            }
        }
    }
    if (!R.Samples.IsEmpty()) { Receivers.Add(MoveTemp(R)); ++GpuTopologyRevision; }
}
bool UThermalWorldSubsystem::IsOccluded(const AThermalSource* Source, const UStaticMeshComponent* Receiver,
                                      const FVector& Emitter, const FVector& Point, const FVector& Normal) const
{
    if (!Source->Occlusion) return false;
    FCollisionQueryParams Params(SCENE_QUERY_STAT(ThermalRadiation), true, Source);
    FHitResult Hit;
    // End slightly outside the receiving surface, so its own final hit does not
    // self-shadow. A different part of the same mesh still blocks radiation.
    if (!GetWorld()->LineTraceSingleByChannel(Hit, Emitter, Point + Normal * 1.0, ECC_Visibility, Params)) return false;
    return !(Hit.GetComponent() == Receiver && FVector::Distance(Hit.ImpactPoint, Point) < 3.0);
}
void UThermalWorldSubsystem::Advance(float Seconds)
{
    ++GpuTemperatureRevision;
    struct FSourceEnergy { double Temperature, Power, FourthPower; };
    TMap<TWeakObjectPtr<AThermalSource>, FSourceEnergy> EnergySources;
    for (const auto& Weak : Sources) if (const auto* Source = Weak.Get()) {
        if (!Source->Enabled) continue;
        const double Temperature = FMath::Max(1.0f, Source->TemperatureKelvin);
        EnergySources.Add(Weak, {Temperature, FMath::Max(0.0f, Source->PowerScale), ThermalMath::FourthPower(Temperature)});
    }
    for (auto& R : Receivers) {
        auto* C = R.Component.Get();
        if (!C) continue;
        const double AmbientFourthPower = ThermalMath::FourthPower(R.BaselineKelvin);
        for (auto& Entry : R.Samples) {
          for (int32 Index = 0; Index < Entry.Value.Num(); ++Index) {
            auto& Sample = Entry.Value[Index];
            double ContactInput = 0, ContactConductance = 0, RadiativeInput = 0, RadiativeCoefficient = 0;
            const auto* BucketTransfers = R.Transfers.Find(Entry.Key);
            if (BucketTransfers && BucketTransfers->IsValidIndex(Index)) for (const auto& Transfer : (*BucketTransfers)[Index]) {
                const auto* Source = EnergySources.Find(Transfer.Source);
                if (!Source) continue;
                const double SourceK = Source->Temperature;
                const double Power = Source->Power;
                const double G = Power * Transfer.ContactConductance;
                const double Q = Power * Sample.Emissivity * Transfer.RadiationViewFactor * ThermalMath::StefanBoltzmann;
                ContactConductance += G; ContactInput += G * SourceK;
                RadiativeCoefficient += Q; RadiativeInput += Q * Source->FourthPower;
            }
            if (ContactConductance == 0 && RadiativeCoefficient == 0 && FMath::IsNearlyEqual(Sample.TemperatureKelvin, R.BaselineKelvin, .001f)) continue;
            // Ambient LWIR exchange uses the same implicit fourth-power solve.
            const double AmbientRadiation = Sample.Emissivity * ThermalMath::StefanBoltzmann;
            Sample.TemperatureKelvin = ThermalMath::IntegrateTransfers(Sample.TemperatureKelvin, R.BaselineKelvin,
                ContactInput, ContactConductance, RadiativeInput + AmbientRadiation * AmbientFourthPower,
                RadiativeCoefficient + AmbientRadiation, Sample.Capacity, FMath::Max(0.f, Sample.Cooling), Seconds);
          }
        }
    }
}
void UThermalWorldSubsystem::RefreshTransfers(double BudgetSeconds)
{
    if (!TransferRefreshPending) return;
    const double Deadline = BudgetSeconds > 0 ? FPlatformTime::Seconds() + BudgetSeconds : TNumericLimits<double>::Max();
    // Keep the previous complete receiver cache active while its replacement
    // is built in small frame budgets. Explicit prewarm completes synchronously.
    while (TransferReceiverIndex < Receivers.Num()) {
        auto& R = Receivers[TransferReceiverIndex];
        const auto* C = R.Component.Get();
        if (!C) { ++TransferReceiverIndex; TransferBucketKeys.Reset(); TransferBucketIndex = 0; continue; }
        if (TransferBucketKeys.IsEmpty()) {
            R.PendingTransfers.Reset();
            R.Samples.GetKeys(TransferBucketKeys);
        }
        const FTransform Transform = ReceiverTransform(R);
        while (TransferBucketIndex < TransferBucketKeys.Num()) {
          const FIntVector Key = TransferBucketKeys[TransferBucketIndex++];
          const auto& Samples = R.Samples.FindChecked(Key);
          auto& BucketTransfers = R.PendingTransfers.FindOrAdd(Key);
          BucketTransfers.SetNum(Samples.Num());
          for (int32 Index = 0; Index < Samples.Num(); ++Index) {
            const FVector Point = Transform.TransformPosition(Samples[Index].LocalPosition);
            const FVector Normal = SurfaceNormal(Transform, Samples[Index].LocalNormal);
            for (const auto& Weak : Sources) {
                const auto* Source = Weak.Get();
                if (!Source) continue;
                const double Contact = Source->HeatParentSurface && Source->GetReceiverActor() == C->GetOwner() &&
                    Source->IsParentMaterialAllowed(Samples[Index].MaterialIndex)
                    ? FMath::Max(0.0f, Source->ParentConductance) * Source->GetContactWeight(Point) : 0;
                double Radiation = Source->GetRadiationWeight(Point, Normal);
                FVector Emitter = Source->GetEmitterPoint(Point);
                if (Source->SourceType == EThermalSourceType::Directional)
                    Emitter = Point - Source->GetActorForwardVector() * FVector::DotProduct(Point - Source->GetActorLocation(), Source->GetActorForwardVector());
                if (Radiation > 1.e-5 && IsOccluded(Source, C, Emitter, Point, Normal)) Radiation = 0;
                if (Contact <= 0 && Radiation <= 1.e-5) continue;
                auto& Transfer = BucketTransfers[Index].AddDefaulted_GetRef();
                Transfer.Source = Weak;
                Transfer.ContactConductance = Contact;
                Transfer.RadiationViewFactor = Radiation;
            }
          }
          if (FPlatformTime::Seconds() >= Deadline) return;
        }
        R.Transfers = MoveTemp(R.PendingTransfers);
        ++TransferReceiverIndex;
        TransferBucketIndex = 0;
        TransferBucketKeys.Reset();
    }
    TransferRefreshPending = false;
}
void UThermalWorldSubsystem::Prewarm(float Seconds)
{
    check(IsInGameThread());
    DiscoverReceivers(true);
    double Left = FMath::Clamp(Seconds, 0.f, 3600.f);
    while (Left > 1.e-6) { const float Step = FMath::Min(.1, Left); Advance(Step); Left -= Step; }
}
void UThermalWorldSubsystem::ResetThermalState()
{
    check(IsInGameThread());
    AccumulatedTime = 0;
    ++GpuTemperatureRevision;
    for (auto& R : Receivers) {
        if (!R.Component.IsValid()) continue;
        const auto Values = ThermalObjectSettings::Resolve(R.Component.Get(), R.BaselineKelvin);
        R.BaselineKelvin = Values.TemperatureKelvin;
        for (auto& Bucket : R.Samples) for (auto& S : Bucket.Value) {
            S.TemperatureKelvin = R.BaselineKelvin;
            if (Values.HasEmissivity) S.Emissivity = Values.Emissivity;
        }
    }
}
int32 UThermalWorldSubsystem::GetSampleCount() const
{
    int32 Count = 0; for (const auto& R : Receivers) for (const auto& Bucket : R.Samples) Count += Bucket.Value.Num(); return Count;
}
FThermalGpuFrame UThermalWorldSubsystem::MakeGpuFrame()
{
    check(IsInGameThread());
    if (!GpuTopology || GpuTopology->Revision != GpuTopologyRevision) {
        GpuTopology = MakeShared<FThermalGpuTopology, ESPMode::ThreadSafe>();
        GpuTopology->Revision = GpuTopologyRevision;
        GpuReceiverBucketOrder.SetNum(Receivers.Num());
        GpuTopology->Samples.Reserve(GetSampleCount());
        for (int32 Index = 0; Index < Receivers.Num(); ++Index) {
            const auto& R = Receivers[Index];
            auto& Keys = GpuReceiverBucketOrder[Index];
            Keys.Reset(); R.Samples.GetKeys(Keys);
            FIntVector Min(MAX_int32), Max(MIN_int32);
            for (const auto& K : Keys) {
                Min.X = FMath::Min(Min.X, K.X); Min.Y = FMath::Min(Min.Y, K.Y); Min.Z = FMath::Min(Min.Z, K.Z);
                Max.X = FMath::Max(Max.X, K.X); Max.Y = FMath::Max(Max.Y, K.Y); Max.Z = FMath::Max(Max.Z, K.Z);
            }
            const FIntVector Size = Max - Min + FIntVector(1);
            FThermalGpuGrid Grid{FIntVector4(Min.X, Min.Y, Min.Z, GpuTopology->Cells.Num()), FIntVector4(Size.X, Size.Y, Size.Z, 0)};
            GpuTopology->Grids.Add(Grid);
            GpuTopology->Cells.AddZeroed(Size.X * Size.Y * Size.Z);
            for (const auto& Key : Keys) {
                const auto& Samples = R.Samples.FindChecked(Key);
                const uint32 First = GpuTopology->Samples.Num();
                for (const auto& S : Samples) GpuTopology->Samples.Add({
                    FVector4f(FVector3f(S.LocalPosition), float(S.MaterialIndex)),
                    FVector4f(FVector3f(S.LocalNormal), 0)});
                GpuTopology->Cells[ThermalGpuData::DenseCellIndex(Grid, Key)] = {First, uint32(Samples.Num())};
            }
        }
        GpuTemperatures.Reset();
    }
    if (!GpuTemperatures || GpuTemperatures->Revision != GpuTemperatureRevision) {
        GpuTemperatures = MakeShared<FThermalGpuTemperatures, ESPMode::ThreadSafe>();
        GpuTemperatures->Revision = GpuTemperatureRevision;
        GpuTemperatures->Values.Reserve(GpuTopology->Samples.Num());
        for (int32 Index = 0; Index < Receivers.Num(); ++Index) {
            const auto& R = Receivers[Index];
            const auto Values = ThermalObjectSettings::Resolve(R.Component.Get(), R.BaselineKelvin);
            FBox Active(ForceInit);
            for (const auto& Key : GpuReceiverBucketOrder[Index])
                for (const auto& S : R.Samples.FindChecked(Key)) {
                    GpuTemperatures->Values.Add(FVector2f(S.TemperatureKelvin, S.Emissivity));
                    if (FMath::Abs(S.TemperatureKelvin - R.BaselineKelvin) > .001f || FMath::Abs(S.Emissivity - Values.Emissivity) > .001f)
                        Active += S.LocalPosition;
                }
            GpuTemperatures->ActiveBounds.Add(Active);
        }
    }
    FThermalGpuFrame Frame;
    Frame.Topology = GpuTopology;
    Frame.Temperatures = GpuTemperatures;
    auto* SimMode = ASimModeBase::getSimMode();
    for (int32 Index = 0; Index < Receivers.Num(); ++Index) {
        const auto& R = Receivers[Index];
        if (!R.Component.IsValid()) { Frame.Receivers.AddDefaulted(); continue; }
        const auto Transform = ReceiverTransform(R);
        const FBox Bounds = R.InstanceIndex == INDEX_NONE ? R.Component->Bounds.GetBox()
            : R.Component->GetStaticMesh()->GetBoundingBox().TransformBy(Transform);
        const FVector Scale = Transform.GetScale3D();
        const auto Reciprocal = [](double V) { return FMath::Abs(V) > KINDA_SMALL_NUMBER ? 1.0 / V : 1.0; };
        FTransform NormalTransform(Transform.GetRotation(), FVector::ZeroVector,
            FVector(Reciprocal(Scale.X), Reciprocal(Scale.Y), Reciprocal(Scale.Z)));
        const auto Values = ThermalObjectSettings::Resolve(R.Component.Get(), R.BaselineKelvin);
        const bool CanSkipCold = Values.HasTemperature && Values.HasEmissivity && FMath::IsNearlyEqual(Values.TemperatureKelvin, R.BaselineKelvin, .001f);
        FBox Active = GpuTemperatures->ActiveBounds[Index];
        if (!CanSkipCold) Active = FBox(FVector(-MAX_flt), FVector(MAX_flt));
        else if (Active.IsValid) Active = Active.ExpandBy(R.SpacingCm * 3);
        else Active = FBox(FVector(MAX_flt), FVector(-MAX_flt));
        const auto& Grid = GpuTopology->Grids[Index];
        Frame.Receivers.Add({FMatrix44f(Transform.ToMatrixWithScale()), FMatrix44f(Transform.ToInverseMatrixWithScale()),
            FMatrix44f(NormalTransform.ToMatrixWithScale()), FVector4f(FVector3f(Bounds.Min), R.SpacingCm), FVector4f(FVector3f(Bounds.Max), 0),
            FVector4f(FVector3f(Active.Min), 0), FVector4f(FVector3f(Active.Max), 0), Grid.MinOffset, Grid.Size});
        FColor Color;
        if (SimMode && SimMode->GetWorld() == GetWorld() && SimMode->GetInstanceSegmentationComponentColor(R.Component.Get(), Color))
            Frame.ReceiversByColor.FindOrAdd((uint32(Color.R) << 16) | (uint32(Color.G) << 8) | Color.B).Add(Index);
    }
    const double Now = FPlatformTime::Seconds();
    if (Now - GpuUniformRefreshTime >= 1.0 || !GpuUniformRefreshTime) {
        GpuUniformActors.Reset();
        for (TActorIterator<AActor> It(GetWorld()); It; ++It)
            if (It->ActorHasTag(TEXT("ThermalBoundsFallback"))) GpuUniformActors.Add(*It);
        GpuUniformRefreshTime = Now;
    }
    for (const auto& Weak : GpuUniformActors) {
        const AActor* Actor = Weak.Get(); if (!Actor) continue;
        FVector Origin, Extent; Actor->GetActorBounds(false, Origin, Extent);
        const auto Values = ThermalObjectSettings::Resolve(Actor->GetRootComponent());
        Frame.UniformSurfaces.Add({FVector4f(FVector3f(Origin - Extent), Values.TemperatureKelvin),
            FVector4f(FVector3f(Origin + Extent), Values.Emissivity)});
    }
    return Frame;
}
FThermalFrameSnapshot UThermalWorldSubsystem::MakeSnapshot() const
{
    check(IsInGameThread());
    FThermalFrameSnapshot Frame;
    auto* SimMode = ASimModeBase::getSimMode();
    Frame.HasSegmentationReceiverMap = SimMode && SimMode->GetWorld() == GetWorld();
    for (const auto& R : Receivers) {
        if (!R.Component.IsValid()) continue;
        auto& Snapshot = Frame.Receivers.AddDefaulted_GetRef();
        Snapshot.Transform = ReceiverTransform(R);
        Snapshot.WorldBounds = R.InstanceIndex == INDEX_NONE ? R.Component->Bounds.GetBox()
            : R.Component->GetStaticMesh()->GetBoundingBox().TransformBy(Snapshot.Transform);
        Snapshot.SpacingCm = R.SpacingCm;
        Snapshot.Samples = R.Samples;
        FColor Color;
        if (Frame.HasSegmentationReceiverMap && SimMode->GetInstanceSegmentationComponentColor(R.Component.Get(), Color))
            Frame.ReceiversByColor.FindOrAdd((uint32(Color.R) << 16) | (uint32(Color.G) << 8) | Color.B).Add(Frame.Receivers.Num()-1);
    }
    for (TActorIterator<AActor> It(GetWorld()); It; ++It) {
        if (!It->ActorHasTag(TEXT("ThermalBoundsFallback"))) continue;
        FVector Origin, Extent;
        It->GetActorBounds(false, Origin, Extent);
        const auto Values = ThermalObjectSettings::Resolve(It->GetRootComponent());
        auto& Surface = Frame.UniformUnannotatedSurfaces.AddDefaulted_GetRef();
        Surface.WorldBounds = FBox(Origin - Extent, Origin + Extent).ExpandBy(25);
        Surface.TemperatureKelvin = Values.TemperatureKelvin;
        Surface.Emissivity = Values.Emissivity;
    }
    return Frame;
}
float UThermalWorldSubsystem::GetSurfaceTemperature(const FVector& Point, const FVector& Normal) const
{
    float Temp = -1, Eps = 0; MakeSnapshot().Sample(Point, Temp, Eps, Normal); return Temp;
}

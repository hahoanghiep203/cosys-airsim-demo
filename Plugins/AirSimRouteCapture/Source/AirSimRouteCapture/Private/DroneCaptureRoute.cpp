#include "DroneCaptureRoute.h"
#include "RouteCaptureBridge.h"
#include "Components/ArrowComponent.h"
#include "Components/TextRenderComponent.h"
#include "Components/SplineComponent.h"
#include "Engine/World.h"
#include "Engine/Engine.h"
#include "EngineUtils.h"
#include "GameFramework/WorldSettings.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformFileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/SecureHash.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonReader.h"
#include "Modules/ModuleManager.h"
#if PLATFORM_WINDOWS
#include "Windows/WindowsHWrapper.h"
#else
#include <cstdio>
#endif

IMPLEMENT_MODULE(FDefaultModuleImpl, AirSimRouteCapture)

namespace {
using FObject = TSharedPtr<FJsonObject>;
FObject Obj() { return MakeShared<FJsonObject>(); }
FObject Vec(const FVector& V) { auto O = Obj(); O->SetNumberField(TEXT("x"), V.X); O->SetNumberField(TEXT("y"), V.Y); O->SetNumberField(TEXT("z"), V.Z); return O; }
FString Full(const FString& Path) { return FPaths::ConvertRelativePathToFull(FPaths::IsRelative(Path) ? FPaths::Combine(FPaths::ProjectDir(), Path) : Path); }
bool Parse(const FString& Text, FObject& Out) { return FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Out) && Out.IsValid(); }
FString Json(const FObject& O) { FString Text; FJsonSerializer::Serialize(O.ToSharedRef(), TJsonWriterFactory<>::Create(&Text)); return Text; }
enum class EPublicationResult { Published, Deferred, Failed };
EPublicationResult Publish(const FString& Path, const FObject& O, uint32* OutSystemError=nullptr)
{
    if (OutSystemError) *OutSystemError=0;
    IFileManager::Get().MakeDirectory(*FPaths::GetPath(Path), true);
    // A distinct candidate also avoids reusing a temporary name whose previous
    // replacement is still held open by an OS scanner or a concurrent reader.
    const FString Temp=Path+TEXT(".")+FGuid::NewGuid().ToString(EGuidFormats::Digits)+TEXT(".tmp");
    if (!FFileHelper::SaveStringToFile(Json(O), *Temp, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM)) {
        IFileManager::Get().Delete(*Temp,false,true,true);
        return EPublicationResult::Failed;
    }
    // Temp is a sibling on the same volume. UE's replace-existing Move deletes
    // the destination first, leaving a missing-file window for the worker. A
    // native replacement keeps the old complete snapshot visible until commit.
#if PLATFORM_WINDOWS
    DWORD LastError=ERROR_SUCCESS;
    for (int32 Attempt=0; Attempt<5; ++Attempt) {
        if (::MoveFileExW(*Temp,*Path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)) return EPublicationResult::Published;
        LastError=::GetLastError();
        if (LastError!=ERROR_SHARING_VIOLATION && LastError!=ERROR_LOCK_VIOLATION && LastError!=ERROR_ACCESS_DENIED) break;
        if (Attempt<4) FPlatformProcess::SleepNoStats(.002f*(Attempt+1));
    }
    // A reader can briefly deny replacement. Preserve the published destination;
    // the next ticker update will write another complete candidate and retry.
    if (OutSystemError) *OutSystemError=LastError;
    IFileManager::Get().Delete(*Temp,false,true,true);
    return LastError==ERROR_SHARING_VIOLATION || LastError==ERROR_LOCK_VIOLATION || LastError==ERROR_ACCESS_DENIED ? EPublicationResult::Deferred : EPublicationResult::Failed;
#else
    const bool Published=::rename(TCHAR_TO_UTF8(*Temp),TCHAR_TO_UTF8(*Path))==0;
    if (!Published) IFileManager::Get().Delete(*Temp,false,true,true);
    return Published ? EPublicationResult::Published : EPublicationResult::Failed;
#endif
}
bool Save(const FString& Path, const FObject& O) { return Publish(Path,O)==EPublicationResult::Published; }
bool LoadShared(const FString& Path, FString& Out)
{
#if PLATFORM_WINDOWS
    // A status handle may outlive replacement of its directory entry. Allow
    // delete sharing so Python os.replace can publish while this read finishes.
    HANDLE Handle=::CreateFileW(*Path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    if (Handle==INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER Size;
    if (!::GetFileSizeEx(Handle,&Size) || Size.QuadPart<0 || Size.QuadPart>4*1024*1024) { ::CloseHandle(Handle); return false; }
    TArray<uint8> Bytes; Bytes.SetNumUninitialized(int32(Size.QuadPart)); DWORD Count=0;
    const bool Ok=Bytes.IsEmpty() || (::ReadFile(Handle,Bytes.GetData(),DWORD(Bytes.Num()),&Count,nullptr) && Count==DWORD(Bytes.Num()));
    ::CloseHandle(Handle);
    if (!Ok) return false;
    FUTF8ToTCHAR Converted(reinterpret_cast<const ANSICHAR*>(Bytes.GetData()),Bytes.Num());
    Out=FString(Converted.Length(),Converted.Get()); return true;
#else
    return FFileHelper::LoadFileToString(Out,*Path);
#endif
}
bool ValidateWithWorker(const FString& Python, const FString& Script, const FString& Path, FString& Error)
{
    if (!FPaths::FileExists(Python) || !FPaths::FileExists(Script)) { Error=TEXT("Configured worker interpreter or script is missing."); return false; }
    int32 ExitCode=-1; FString StdOut, StdErr;
    const FString Args=FString::Printf(TEXT("\"%s\" --mission \"%s\" --validate-only"),*Script,*Path);
    if (!FPlatformProcess::ExecProcess(*Python,*Args,&ExitCode,&StdOut,&StdErr,*FPaths::ProjectDir(),true) || ExitCode!=0) { Error=TEXT("JSON validation failed: ")+StdErr.Left(2000); return false; }
    return true;
}
FObject NodeJson(const FRouteNodeSettings& S)
{
    auto O = Obj(); O->SetStringField(TEXT("behavior"), S.bFlyThrough ? TEXT("fly_through") : TEXT("stop"));
    O->SetNumberField(TEXT("arrival_radius_m"), S.ArrivalRadiusM); O->SetNumberField(TEXT("max_settled_speed_mps"), S.MaxSettledSpeedMps);
    O->SetNumberField(TEXT("aim_tolerance_deg"), S.AimToleranceDeg); O->SetNumberField(TEXT("settle_time_ms"), S.SettleTimeMs); O->SetNumberField(TEXT("extra_hold_ms"), S.ExtraHoldMs);
    auto C = Obj(); C->SetStringField(TEXT("mode"), S.Capture == ERouteNodeCapture::Off ? TEXT("off") : S.Capture == ERouteNodeCapture::Single ? TEXT("single") : TEXT("burst"));
    if (S.Capture != ERouteNodeCapture::Off) C->SetNumberField(TEXT("delay_ms"), S.DelayMs);
    if (S.Capture == ERouteNodeCapture::Burst) { C->SetNumberField(TEXT("count"), S.BurstCount); C->SetNumberField(TEXT("interval_ms"), S.BurstIntervalMs); }
    O->SetObjectField(TEXT("capture"), C); return O;
}
FObject SegmentJson(const FRouteSegmentSettings& S)
{
    auto O = Obj(); O->SetNumberField(TEXT("speed_mps"), S.SpeedMps); O->SetNumberField(TEXT("acceleration_mps2"), S.AccelerationMps2); O->SetNumberField(TEXT("deceleration_mps2"), S.DecelerationMps2); O->SetNumberField(TEXT("timeout_s"), S.TimeoutS);
    auto C = Obj(); C->SetStringField(TEXT("mode"), S.Capture == ERouteTravelCapture::Off ? TEXT("off") : S.Capture == ERouteTravelCapture::TimeInterval ? TEXT("time_interval") : TEXT("distance_interval"));
    if (S.Capture == ERouteTravelCapture::TimeInterval) C->SetNumberField(TEXT("interval_ms"), S.IntervalMs);
    if (S.Capture == ERouteTravelCapture::DistanceInterval) C->SetNumberField(TEXT("interval_m"), S.IntervalM);
    O->SetObjectField(TEXT("capture"), C); return O;
}
FString GeneratedSegmentId(const FString& From, const FString& To)
{
    // Include lengths in the hash input so endpoint separators are unambiguous.
    // Prefixes aid inspection; the full digest keeps long IDs within 80 chars.
    const FString Key=FString::Printf(TEXT("%d:%s%d:%s"),From.Len(),*From,To.Len(),*To);
    return FString::Printf(TEXT("S_%s_to_%s_%s"),*From.Left(16),*To.Left(16),*FMD5::HashAnsiString(*Key));
}
FObject Merged(const FObject& Base, const FObject& Override)
{
    auto O = Obj(); O->Values = Base->Values;
    if (Override) for (const auto& Pair : Override->Values) O->Values.Add(Pair.Key, Pair.Value);
    return O;
}
void ReadNode(const FObject& O, FRouteNodeSettings& S)
{
    S.bFlyThrough = O->GetStringField(TEXT("behavior")) == TEXT("fly_through");
    S.ArrivalRadiusM = O->GetNumberField(TEXT("arrival_radius_m")); S.MaxSettledSpeedMps = O->GetNumberField(TEXT("max_settled_speed_mps")); S.AimToleranceDeg = O->GetNumberField(TEXT("aim_tolerance_deg"));
    S.SettleTimeMs = O->GetIntegerField(TEXT("settle_time_ms")); S.ExtraHoldMs = O->GetIntegerField(TEXT("extra_hold_ms"));
    auto C = O->GetObjectField(TEXT("capture")); const FString Mode = C->GetStringField(TEXT("mode"));
    S.Capture = Mode == TEXT("off") ? ERouteNodeCapture::Off : Mode == TEXT("single") ? ERouteNodeCapture::Single : ERouteNodeCapture::Burst;
    if (S.Capture != ERouteNodeCapture::Off) S.DelayMs = C->GetIntegerField(TEXT("delay_ms"));
    if (S.Capture == ERouteNodeCapture::Burst) { S.BurstCount = C->GetIntegerField(TEXT("count")); S.BurstIntervalMs = C->GetIntegerField(TEXT("interval_ms")); }
}
void ReadSegment(const FObject& O, FRouteSegmentSettings& S)
{
    S.SpeedMps = O->GetNumberField(TEXT("speed_mps")); S.AccelerationMps2 = O->GetNumberField(TEXT("acceleration_mps2")); S.DecelerationMps2 = O->GetNumberField(TEXT("deceleration_mps2")); S.TimeoutS = O->GetNumberField(TEXT("timeout_s"));
    auto C = O->GetObjectField(TEXT("capture")); const FString Mode = C->GetStringField(TEXT("mode"));
    S.Capture = Mode == TEXT("off") ? ERouteTravelCapture::Off : Mode == TEXT("time_interval") ? ERouteTravelCapture::TimeInterval : ERouteTravelCapture::DistanceInterval;
    if (S.Capture == ERouteTravelCapture::TimeInterval) S.IntervalMs = C->GetIntegerField(TEXT("interval_ms"));
    if (S.Capture == ERouteTravelCapture::DistanceInterval) S.IntervalM = C->GetNumberField(TEXT("interval_m"));
}
bool ValidNode(const FRouteNodeSettings& S)
{
    return FMath::IsFinite(S.ArrivalRadiusM) && S.ArrivalRadiusM > 0 && FMath::IsFinite(S.MaxSettledSpeedMps) && S.MaxSettledSpeedMps > 0 && FMath::IsFinite(S.AimToleranceDeg) && S.AimToleranceDeg > 0 && S.AimToleranceDeg <= 180 && S.SettleTimeMs >= 0 && S.ExtraHoldMs >= 0 && S.DelayMs >= 0 && (S.Capture != ERouteNodeCapture::Burst || (S.BurstCount >= 2 && S.BurstCount <= 10000 && S.BurstIntervalMs > 0)) && (!S.bFlyThrough || (S.Capture == ERouteNodeCapture::Off && S.SettleTimeMs == 0 && S.ExtraHoldMs == 0));
}
bool ValidSegment(const FRouteSegmentSettings& S)
{
    return FMath::IsFinite(S.SpeedMps) && S.SpeedMps > 0 && FMath::IsFinite(S.AccelerationMps2) && S.AccelerationMps2 > 0 && FMath::IsFinite(S.DecelerationMps2) && S.DecelerationMps2 > 0 && FMath::IsFinite(S.TimeoutS) && S.TimeoutS > 0 && (S.Capture != ERouteTravelCapture::TimeInterval || S.IntervalMs > 0) && (S.Capture != ERouteTravelCapture::DistanceInterval || (FMath::IsFinite(S.IntervalM) && S.IntervalM > 0));
}
bool ValidId(const FString& Id)
{
    if (Id.IsEmpty() || Id.Len() > 80 || !FChar::IsAlpha(Id[0])) return false;
    for (TCHAR C : Id) if (!FChar::IsAlnum(C) && C != TEXT('_') && C != TEXT('-')) return false;
    return true;
}
bool HasFields(const FObject& O, EJson Type, std::initializer_list<const TCHAR*> Fields)
{
    if (!O) return false;
    for (auto Field : Fields) { const auto V = O->Values.Find(Field); if (!V || !V->IsValid() || (*V)->Type != Type) return false; }
    return true;
}
bool NodeShape(const FObject& O)
{
    if (!HasFields(O, EJson::String, {TEXT("behavior")}) || !HasFields(O, EJson::Number, {TEXT("arrival_radius_m"), TEXT("max_settled_speed_mps"), TEXT("aim_tolerance_deg"), TEXT("settle_time_ms"), TEXT("extra_hold_ms")}) || !HasFields(O, EJson::Object, {TEXT("capture")})) return false;
    auto C = O->GetObjectField(TEXT("capture")); if (!HasFields(C,EJson::String,{TEXT("mode")})) return false;
    const FString Mode = C->GetStringField(TEXT("mode"));
    return Mode == TEXT("off") || (HasFields(C,EJson::Number,{TEXT("delay_ms")}) && (Mode == TEXT("single") || (Mode == TEXT("burst") && HasFields(C,EJson::Number,{TEXT("count"),TEXT("interval_ms")}))));
}
bool SegmentShape(const FObject& O)
{
    if (!HasFields(O,EJson::Number,{TEXT("speed_mps"),TEXT("acceleration_mps2"),TEXT("deceleration_mps2"),TEXT("timeout_s")}) || !HasFields(O,EJson::Object,{TEXT("capture")})) return false;
    auto C=O->GetObjectField(TEXT("capture")); if (!HasFields(C,EJson::String,{TEXT("mode")})) return false;
    auto Mode=C->GetStringField(TEXT("mode"));
    return Mode==TEXT("off") || (Mode==TEXT("time_interval") && HasFields(C,EJson::Number,{TEXT("interval_ms")})) || (Mode==TEXT("distance_interval") && HasFields(C,EJson::Number,{TEXT("interval_m")}));
}
bool ImportShape(const FObject& M)
{
    if (!HasFields(M,EJson::String,{TEXT("schema_version"),TEXT("format"),TEXT("mission_id"),TEXT("name"),TEXT("map_asset")}) || M->GetStringField(TEXT("schema_version")) != TEXT("1.0.0") || M->GetStringField(TEXT("format")) != TEXT("airsim-route-capture") || !HasFields(M,EJson::Object,{TEXT("defaults"),TEXT("connection"),TEXT("camera"),TEXT("thermal"),TEXT("output"),TEXT("flight"),TEXT("limits")}) || !HasFields(M,EJson::Array,{TEXT("nodes"),TEXT("segments")})) return false;
    auto D=M->GetObjectField(TEXT("defaults"));
    if (!HasFields(D,EJson::Object,{TEXT("node"),TEXT("segment")}) || !NodeShape(D->GetObjectField(TEXT("node"))) || !SegmentShape(D->GetObjectField(TEXT("segment")))) return false;
    if (!HasFields(M->GetObjectField(TEXT("connection")),EJson::String,{TEXT("vehicle_name"),TEXT("camera_name")}) || !HasFields(M->GetObjectField(TEXT("connection")),EJson::Number,{TEXT("port")})) return false;
    if (!HasFields(M->GetObjectField(TEXT("camera")),EJson::Number,{TEXT("width_px"),TEXT("height_px"),TEXT("horizontal_fov_deg")})) return false;
    auto T=M->GetObjectField(TEXT("thermal"));
    if (!HasFields(T,EJson::Number,{TEXT("warmup_ms")}) || !HasFields(T,EJson::Object,{TEXT("display_window_k")}) || !HasFields(T->GetObjectField(TEXT("display_window_k")),EJson::Number,{TEXT("min"),TEXT("max")}) || !HasFields(M->GetObjectField(TEXT("output")),EJson::String,{TEXT("root")})) return false;
    const auto& Nodes=M->GetArrayField(TEXT("nodes")); const auto& Segments=M->GetArrayField(TEXT("segments"));
    if (Nodes.Num()<2 || Segments.Num()!=Nodes.Num()-1) return false;
    TSet<FString> Ids;
    for (const auto& V:Nodes) {
        if (!V || V->Type!=EJson::Object) return false; auto N=V->AsObject();
        if (!HasFields(N,EJson::String,{TEXT("id"),TEXT("label")}) || !HasFields(N,EJson::Object,{TEXT("position_cm"),TEXT("camera_rotation_deg")})) return false;
        auto Id=N->GetStringField(TEXT("id")); if (!ValidId(Id) || Ids.Contains(Id)) return false; Ids.Add(Id);
        if (!HasFields(N->GetObjectField(TEXT("position_cm")),EJson::Number,{TEXT("x"),TEXT("y"),TEXT("z")}) || !HasFields(N->GetObjectField(TEXT("camera_rotation_deg")),EJson::Number,{TEXT("pitch"),TEXT("yaw"),TEXT("roll")})) return false;
        const FObject* S; if (N->TryGetObjectField(TEXT("settings"),S) && !NodeShape(Merged(D->GetObjectField(TEXT("node")),*S))) return false;
    }
    for (int32 I=0; I<Segments.Num(); ++I) {
        if (!Segments[I] || Segments[I]->Type!=EJson::Object) return false; auto S=Segments[I]->AsObject();
        if (!HasFields(S,EJson::String,{TEXT("id"),TEXT("from"),TEXT("to")}) || S->GetStringField(TEXT("from"))!=Nodes[I]->AsObject()->GetStringField(TEXT("id")) || S->GetStringField(TEXT("to"))!=Nodes[I+1]->AsObject()->GetStringField(TEXT("id"))) return false;
        const FObject* Settings; if (S->TryGetObjectField(TEXT("settings"),Settings) && !SegmentShape(Merged(D->GetObjectField(TEXT("segment")),*Settings))) return false;
    }
    return true;
}
}

ADroneRoutePoint::ADroneRoutePoint()
{
    RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    Direction = CreateDefaultSubobject<UArrowComponent>(TEXT("CameraDirection")); Direction->SetupAttachment(RootComponent); Direction->ArrowColor = FColor::Cyan; Direction->ArrowSize = 2;
    Number = CreateDefaultSubobject<UTextRenderComponent>(TEXT("PointNumber")); Number->SetupAttachment(RootComponent); Number->SetRelativeLocation(FVector(0, 0, 45)); Number->SetWorldSize(60); Number->SetTextRenderColor(FColor::Yellow); Number->SetHorizontalAlignment(EHTA_Center);
    SetActorEnableCollision(false); Tags.Add(TEXT("ThermalIgnore")); Tags.Add(TEXT("RouteCaptureMarker"));
}
void ADroneRoutePoint::UpdateNumber(int32 Value) { DisplayNumber = Value; Number->SetText(FText::FromString(FString::Printf(TEXT("%02d %s"), Value, *PointLabel))); }
void ADroneRoutePoint::OnConstruction(const FTransform& Transform)
{
    Super::OnConstruction(Transform);
    if (PointId.IsEmpty()) PointId = TEXT("P_") + FGuid::NewGuid().ToString(EGuidFormats::Digits);
    UpdateNumber(DisplayNumber); Direction->SetHiddenInGame(!bDemoVisibleInGame); Number->SetHiddenInGame(!bDemoVisibleInGame);
}
void ADroneRoutePoint::BeginPlay() { Super::BeginPlay(); FRouteCaptureBridge::HideMarkersFromDroneCameras(GetWorld()); }
void ADroneRoutePoint::PostDuplicate(EDuplicateMode::Type Mode) { Super::PostDuplicate(Mode); if (Mode == EDuplicateMode::Normal) PointId = TEXT("P_") + FGuid::NewGuid().ToString(EGuidFormats::Digits); }

ADroneCaptureRoute::ADroneCaptureRoute()
{
    RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    Preview = CreateDefaultSubobject<USplineComponent>(TEXT("StraightRoutePreview")); Preview->SetupAttachment(RootComponent); Preview->SetDrawDebug(true); Preview->SetHiddenInGame(true);
    SetActorEnableCollision(false); Tags.Add(TEXT("ThermalIgnore")); Tags.Add(TEXT("RouteCaptureMarker"));
}
void ADroneCaptureRoute::OnConstruction(const FTransform& T) { Super::OnConstruction(T); if (RouteId.IsEmpty()) RouteId = TEXT("R_") + FGuid::NewGuid().ToString(EGuidFormats::Digits); RefreshPreview(); }
void ADroneCaptureRoute::PostDuplicate(EDuplicateMode::Type Mode) { Super::PostDuplicate(Mode); if (Mode==EDuplicateMode::Normal) RouteId=TEXT("R_")+FGuid::NewGuid().ToString(EGuidFormats::Digits); }
void ADroneCaptureRoute::RefreshPreview()
{
    Preview->ClearSplinePoints(false); int32 N = 0;
    for (ADroneRoutePoint* P : OrderedPoints) if (IsValid(P)) { P->UpdateNumber(P->bEnabled ? ++N : 0); if (P->bEnabled) { Preview->AddSplinePoint(P->GetActorLocation(), ESplineCoordinateSpace::World, false); Preview->SetSplinePointType(N-1, ESplinePointType::Linear, false); } }
    Preview->UpdateSpline();
}
void ADroneCaptureRoute::BeginPlay()
{
    Super::BeginPlay(); FRouteCaptureBridge::HideMarkersFromDroneCameras(GetWorld());
    Ticker = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateUObject(this, &ADroneCaptureRoute::Supervise), .05f);
}
void ADroneCaptureRoute::EndPlay(const EEndPlayReason::Type Reason)
{
    if (IsWorkerRunning()) SendControl(TEXT("stop"));
    FTSTicker::GetCoreTicker().RemoveTicker(Ticker);
    if (Worker.IsValid()) {
        if (IsWorkerRunning()) {
            // PIE teardown cannot pump the RPC game-thread queue. Clear the owned
            // process and explicitly record that hover could not be acknowledged.
            FPlatformProcess::TerminateProc(Worker, true);
            auto O=Obj(); O->SetStringField(TEXT("reason"),TEXT("Play world closed while worker active")); O->SetBoolField(TEXT("recovery_acknowledged"),false); Save(FPaths::Combine(RunDirectory,TEXT("native_supervisor.json")),O);
        }
        FPlatformProcess::CloseProc(Worker); Worker.Reset();
    }
    Super::EndPlay(Reason);
}
bool ADroneCaptureRoute::IsWorkerRunning() const { return Worker.IsValid() && FPlatformProcess::IsProcRunning(Worker); }
FString ADroneCaptureRoute::ValidateRoute()
{
    if (!ValidId(RouteId)) return Status = TEXT("Invalid route ID.");
    if (!ValidNode(DefaultNode) || !ValidSegment(DefaultSegment)) return Status = TEXT("Invalid default node/segment settings (fly-through requires capture/settle/hold off).");
    TSet<FString> Ids; int32 Count = 0;
    for (ADroneRoutePoint* P : OrderedPoints) {
        if (!IsValid(P)) return Status = TEXT("Route has a missing point reference.");
        if (!P->bEnabled) continue;
        if (!ValidId(P->PointId) || Ids.Contains(P->PointId)) return Status = TEXT("Point IDs must be valid and unique.");
        if (P->PointLabel.IsEmpty() || P->GetActorTransform().ContainsNaN() || (P->bOverrideSettings && !ValidNode(P->Settings))) return Status = TEXT("Invalid point transform or node settings.");
        Ids.Add(P->PointId); ++Count;
    }
    if (Count < 2) return Status = TEXT("Route needs at least two enabled points.");
    TSet<FString> OverridePairs, AuthoredSegmentIds;
    for (const auto& S : SegmentOverrides) {
        if (!IsValid(S.From) || !IsValid(S.To) || (S.bOverrideSettings && !ValidSegment(S.Settings))) return Status = TEXT("Invalid explicit segment override.");
        if (!S.SegmentId.IsEmpty()) {
            if (!ValidId(S.SegmentId) || AuthoredSegmentIds.Contains(S.SegmentId)) return Status=TEXT("Segment IDs must be valid and unique.");
            AuthoredSegmentIds.Add(S.SegmentId);
        }
        const FString Key=S.From->PointId+TEXT("/")+S.To->PointId;
        if (OverridePairs.Contains(Key)) return Status=TEXT("Duplicate overrides for the same explicit segment.");
        OverridePairs.Add(Key);
    }
    if (WidthPx <= 0 || HeightPx <= 0 || !FMath::IsFinite(HorizontalFovDeg) || HorizontalFovDeg <= 0 || HorizontalFovDeg >= 180 || WarmupMs < 0 || !FMath::IsFinite(ThermalMinK) || !FMath::IsFinite(ThermalMaxK) || ThermalMinK <= 0 || ThermalMaxK <= ThermalMinK || RpcPort < 1 || RpcPort > 65535 || OutputRoot.IsEmpty()) return Status = TEXT("Invalid camera, thermal, connection or output settings.");
    return Status = TEXT("Valid");
}
FObject ADroneCaptureRoute::MakeMission(FString& Error) const
{
    FObject O; FString Text = MissionTemplateJson;
    if (Text.IsEmpty()) FFileHelper::LoadFileToString(Text, *FPaths::Combine(IPluginManager::Get().FindPlugin(TEXT("AirSimRouteCapture"))->GetBaseDir(), TEXT("Content/mission.default.json")));
    if (!Parse(Text, O)) { Error = TEXT("Mission template is not valid JSON."); return nullptr; }
    if (!ImportShape(O)) { Error = TEXT("Mission template has invalid structure/version."); return nullptr; }
    O->SetStringField(TEXT("mission_id"), RouteId); O->SetStringField(TEXT("name"), RouteName);
    const FString Map = UWorld::RemovePIEPrefix(GetWorld()->GetOutermost()->GetName());
    if (MissionTemplateJson.IsEmpty()) O->SetStringField(TEXT("map_asset"), Map);
    auto C = O->GetObjectField(TEXT("connection")); C->SetStringField(TEXT("vehicle_name"), VehicleName); C->SetStringField(TEXT("camera_name"), CameraName); C->SetNumberField(TEXT("port"), RpcPort);
    C = O->GetObjectField(TEXT("camera")); C->SetNumberField(TEXT("width_px"), WidthPx); C->SetNumberField(TEXT("height_px"), HeightPx); C->SetNumberField(TEXT("horizontal_fov_deg"), HorizontalFovDeg);
    C = O->GetObjectField(TEXT("thermal")); C->SetNumberField(TEXT("warmup_ms"), WarmupMs); auto Window = C->GetObjectField(TEXT("display_window_k")); Window->SetNumberField(TEXT("min"), ThermalMinK); Window->SetNumberField(TEXT("max"), ThermalMaxK);
    O->GetObjectField(TEXT("output"))->SetStringField(TEXT("root"), Full(OutputRoot));
    auto D = O->GetObjectField(TEXT("defaults")); D->SetObjectField(TEXT("node"), NodeJson(DefaultNode)); D->SetObjectField(TEXT("segment"), SegmentJson(DefaultSegment));
    TArray<TSharedPtr<FJsonValue>> Nodes, Segments; TSet<FString> SegmentIds; ADroneRoutePoint* Previous = nullptr;
    for (ADroneRoutePoint* P : OrderedPoints) if (IsValid(P) && P->bEnabled) {
        auto N = Obj(); N->SetStringField(TEXT("id"), P->PointId); N->SetStringField(TEXT("label"), P->PointLabel); N->SetObjectField(TEXT("position_cm"), Vec(P->GetActorLocation()));
        auto R = Obj(); const auto Rot = P->GetActorRotation().GetNormalized(); R->SetNumberField(TEXT("pitch"), Rot.Pitch); R->SetNumberField(TEXT("yaw"), Rot.Yaw); R->SetNumberField(TEXT("roll"), Rot.Roll); N->SetObjectField(TEXT("camera_rotation_deg"), R);
        if (P->bOverrideSettings) N->SetObjectField(TEXT("settings"), NodeJson(P->Settings)); Nodes.Add(MakeShared<FJsonValueObject>(N));
        if (Previous) { auto S = Obj(); FString Id=GeneratedSegmentId(Previous->PointId,P->PointId); S->SetStringField(TEXT("from"), Previous->PointId); S->SetStringField(TEXT("to"), P->PointId);
            for (const auto& Override : SegmentOverrides) if (Override.From == Previous && Override.To == P) {
                if (!Override.SegmentId.IsEmpty()) Id=Override.SegmentId;
                if (Override.bOverrideSettings) S->SetObjectField(TEXT("settings"), SegmentJson(Override.Settings));
                break;
            }
            if (SegmentIds.Contains(Id)) { Error=TEXT("Exported segment IDs must be unique."); return nullptr; }
            SegmentIds.Add(Id); S->SetStringField(TEXT("id"),Id);
            Segments.Add(MakeShared<FJsonValueObject>(S)); }
        Previous = P;
    }
    O->SetArrayField(TEXT("nodes"), Nodes); O->SetArrayField(TEXT("segments"), Segments); return O;
}
bool ADroneCaptureRoute::ExportMission()
{
    if (ValidateRoute() != TEXT("Valid")) return false;
    FString Error; auto M = MakeMission(Error); if (!M || !Save(Full(JsonFile), M)) { Status = Error.IsEmpty() ? TEXT("Could not write mission JSON.") : Error; return false; }
    Status = TEXT("Exported ") + Full(JsonFile); return true;
}
bool ADroneCaptureRoute::ImportMission()
{
    FString Text; FObject M;
    if (!FFileHelper::LoadFileToString(Text, *Full(JsonFile)) || !Parse(Text, M) || !ImportShape(M)) { Status = TEXT("Invalid mission JSON structure/version/order."); return false; }
    const FString Script=FPaths::Combine(IPluginManager::Get().FindPlugin(TEXT("AirSimRouteCapture"))->GetBaseDir(),TEXT("Scripts/route_capture.py"));
    FString ValidationError;
    if (!ValidateWithWorker(Full(PythonExecutable),Script,Full(JsonFile),ValidationError)) { Status=ValidationError; return false; }
    // Strict schema/semantic validation occurs before any actor mutation. Reuse
    // stable IDs when switching presets; retain unrelated actors/references.
    const auto Defaults = M->GetObjectField(TEXT("defaults"));
    const FObject* DN; const FObject* DS;
    if (!Defaults->TryGetObjectField(TEXT("node"), DN) || !Defaults->TryGetObjectField(TEXT("segment"), DS) || M->GetArrayField(TEXT("nodes")).Num() < 2) { Status = TEXT("Missing defaults or nodes."); return false; }
    TMap<FString,ADroneRoutePoint*> Existing;
    for (ADroneRoutePoint* P:OrderedPoints) if (IsValid(P)) Existing.Add(P->PointId,P);
    Modify();
    TArray<TObjectPtr<ADroneRoutePoint>> NewPoints;
    for (const auto& Value : M->GetArrayField(TEXT("nodes"))) {
        const auto N = Value->AsObject(); const FObject* P; const FObject* R;
        if (!N || !N->TryGetObjectField(TEXT("position_cm"), P) || !N->TryGetObjectField(TEXT("camera_rotation_deg"), R) || !N->HasTypedField<EJson::String>(TEXT("id")) || !N->HasTypedField<EJson::String>(TEXT("label"))) { Status = TEXT("Invalid node JSON."); return false; }
        const FVector Position((*P)->GetNumberField(TEXT("x")), (*P)->GetNumberField(TEXT("y")), (*P)->GetNumberField(TEXT("z")));
        const FRotator Rotation((*R)->GetNumberField(TEXT("pitch")), (*R)->GetNumberField(TEXT("yaw")), (*R)->GetNumberField(TEXT("roll")));
        ADroneRoutePoint* Point=Existing.FindRef(N->GetStringField(TEXT("id")));
        if (!Point) { Point=GetWorld()->SpawnActor<ADroneRoutePoint>(Position,Rotation); Point->SetFlags(RF_Transactional); }
        else { Point->Modify(); Point->SetActorLocationAndRotation(Position,Rotation); }
        Point->PointId = N->GetStringField(TEXT("id")); Point->PointLabel = N->GetStringField(TEXT("label")); Point->bEnabled=true; Point->bOverrideSettings=false;
        const FObject* Settings; if (N->TryGetObjectField(TEXT("settings"), Settings)) { Point->bOverrideSettings = true; ReadNode(Merged(*DN, *Settings), Point->Settings); }
        NewPoints.Add(Point);
    }
    OrderedPoints = NewPoints; SegmentOverrides.Reset(); ReadNode(*DN, DefaultNode); ReadSegment(*DS, DefaultSegment);
    if (M->HasTypedField<EJson::Array>(TEXT("segments"))) for (const auto& V : M->GetArrayField(TEXT("segments"))) { const auto S = V->AsObject(); const FObject* Settings=nullptr; if (!S) continue;
        FDroneRouteSegment Segment; Segment.SegmentId=S->GetStringField(TEXT("id"));
        for (ADroneRoutePoint* P : OrderedPoints) { if (P->PointId == S->GetStringField(TEXT("from"))) Segment.From = P; if (P->PointId == S->GetStringField(TEXT("to"))) Segment.To = P; }
        Segment.bOverrideSettings=S->TryGetObjectField(TEXT("settings"),Settings);
        ReadSegment(Segment.bOverrideSettings ? Merged(*DS,*Settings) : *DS,Segment.Settings); SegmentOverrides.Add(Segment); }
    RouteId = M->GetStringField(TEXT("mission_id")); RouteName = M->GetStringField(TEXT("name")); auto C = M->GetObjectField(TEXT("connection")); VehicleName = C->GetStringField(TEXT("vehicle_name")); CameraName = C->GetStringField(TEXT("camera_name")); RpcPort = C->GetIntegerField(TEXT("port"));
    C = M->GetObjectField(TEXT("camera")); WidthPx = C->GetIntegerField(TEXT("width_px")); HeightPx = C->GetIntegerField(TEXT("height_px")); HorizontalFovDeg = C->GetNumberField(TEXT("horizontal_fov_deg"));
    C = M->GetObjectField(TEXT("thermal")); WarmupMs = C->GetIntegerField(TEXT("warmup_ms")); ThermalMinK = C->GetObjectField(TEXT("display_window_k"))->GetNumberField(TEXT("min")); ThermalMaxK = C->GetObjectField(TEXT("display_window_k"))->GetNumberField(TEXT("max"));
    OutputRoot = M->GetObjectField(TEXT("output"))->GetStringField(TEXT("root")); MissionTemplateJson = Text; RefreshPreview(); MarkPackageDirty(); Status = TEXT("Imported mission. ") + ValidateRoute(); return true;
}

bool ADroneCaptureRoute::WriteContext(const FObject& Mission, FString& Error)
{
    FRouteCaptureVehicleContext C;
    if (!FRouteCaptureBridge::Resolve(GetWorld(), VehicleName, CameraName, C, Error)) return false;
    if (C.SimMode != TEXT("Multirotor")) { Error = TEXT("Route capture requires a Multirotor Play session."); return false; }
    if (GetWorld()->GetWorldSettings()->bEnableWorldOriginRebasing || C.WorldOrigin != FIntVector::ZeroValue) { Error = TEXT("World-origin rebasing is unsupported."); return false; }
    const FString ActualMap=UWorld::RemovePIEPrefix(GetWorld()->GetOutermost()->GetName());
    if (ActualMap != Mission->GetStringField(TEXT("map_asset"))) { Error=TEXT("Mission map_asset does not match the active Play world."); return false; }
    InitialWorldOrigin = C.WorldOrigin;
    auto O = Obj(); O->SetStringField(TEXT("schema_version"), TEXT("1.0.0")); O->SetStringField(TEXT("vehicle_name"), VehicleName); O->SetNumberField(TEXT("world_to_meters"), C.WorldToMeters); O->SetObjectField(TEXT("vehicle_origin_ue_cm"), Vec(C.Origin)); O->SetObjectField(TEXT("world_origin_ue_cm"), Vec(FVector(C.WorldOrigin)));
    O->SetStringField(TEXT("map_asset"), ActualMap); O->SetStringField(TEXT("sim_mode"), C.SimMode); O->SetStringField(TEXT("vehicle_type"), C.VehicleType); O->SetStringField(TEXT("sim_clock_path"), FPaths::Combine(RunDirectory, TEXT("clock.json")));
    auto Clock = Obj(); Clock->SetStringField(TEXT("source"), TEXT("UWorld::GetTimeSeconds")); Clock->SetStringField(TEXT("domain"), TEXT("unpaused_simulation_time")); Clock->SetNumberField(TEXT("time_dilation"), GetWorld()->GetWorldSettings()->GetEffectiveTimeDilation()); O->SetObjectField(TEXT("clock_config"), Clock);
    auto Profile = Obj(); auto Camera = Obj(); Camera->SetNumberField(TEXT("width_px"), C.Width); Camera->SetNumberField(TEXT("height_px"), C.Height); Camera->SetNumberField(TEXT("horizontal_fov_deg"), C.Fov); Camera->SetStringField(TEXT("projection"), C.Projection); Profile->SetObjectField(TEXT("camera"), Camera);
    auto Thermal = Obj(); auto Window = Obj(); Window->SetNumberField(TEXT("min"), C.ThermalMin); Window->SetNumberField(TEXT("max"), C.ThermalMax); Thermal->SetObjectField(TEXT("display_window_k"), Window); Profile->SetObjectField(TEXT("thermal"), Thermal); O->SetObjectField(TEXT("active_profile"), Profile);
    FVector BoundsOrigin, BoundsExtent; C.Pawn->GetActorBounds(true,BoundsOrigin,BoundsExtent);
    const double Clearance = FMath::Max(Mission->GetObjectField(TEXT("limits"))->GetNumberField(TEXT("obstacle_clearance_m")),BoundsExtent.Size()/C.WorldToMeters);
    SnapshotClearanceM=Clearance;
    FCollisionQueryParams Query(SCENE_QUERY_STAT(RouteCaptureClearance), false); Query.AddIgnoredActor(C.Pawn.Get());
    SnapshotMarkerActors.Reset();
    for (TActorIterator<AActor> It(GetWorld()); It; ++It) if (It->ActorHasTag(TEXT("RouteCaptureMarker"))) { SnapshotMarkerActors.Add(*It); Query.AddIgnoredActor(*It); }
    auto CheckLeg = [&](const FVector& A, const FVector& B) {
        FHitResult Hit;
        if (GetWorld()->SweepSingleByChannel(Hit, A, B, FQuat::Identity, ECC_WorldStatic, FCollisionShape::MakeSphere(Clearance*C.WorldToMeters), Query)) { Error = FString::Printf(TEXT("Clearance sweep blocked by %s."), *GetNameSafe(Hit.GetActor())); return false; }
        return true;
    };
    // Exclude ordinary landed contact at the takeoff pad; check the ascent above
    // the clearance radius, the entry leg and every straight route segment.
    const double Height = Mission->GetObjectField(TEXT("flight"))->GetObjectField(TEXT("takeoff"))->GetNumberField(TEXT("height_above_takeoff_m"))*C.WorldToMeters;
    FVector Previous = C.BodyPosition;
    if (C.Landed) {
        Previous += FVector(0,0,Height);
        if (!CheckLeg(C.BodyPosition+FVector(0,0,Clearance*C.WorldToMeters+1), Previous)) return false;
    }
    TArray<TSharedPtr<FJsonValue>> Resolved;
    for (ADroneRoutePoint* P : OrderedPoints) if (IsValid(P) && P->bEnabled) {
        if (!CheckLeg(Previous, P->GetActorLocation())) return false; Previous = P->GetActorLocation();
        FVector Ned; if (!FRouteCaptureBridge::ToLocalNed(GetWorld(), VehicleName, Previous, Ned, Error)) return false;
        auto N = Obj(); N->SetStringField(TEXT("id"), P->PointId); N->SetObjectField(TEXT("position_ned_m"), Vec(Ned)); Resolved.Add(MakeShared<FJsonValueObject>(N));
    }
    O->SetArrayField(TEXT("resolved_nodes"), Resolved); auto Path = Obj(); Path->SetBoolField(TEXT("clear"), true); Path->SetNumberField(TEXT("clearance_m"), Clearance); Path->SetStringField(TEXT("method"), TEXT("native_sphere_sweep_takeoff_entry_and_segments")); O->SetObjectField(TEXT("path_validation"), Path);
    return Save(FPaths::Combine(RunDirectory, TEXT("context.json")), O);
}

bool ADroneCaptureRoute::Start()
{
    if (!GetWorld() || !GetWorld()->IsGameWorld()) { Status = TEXT("Enter Play before Start; Play alone does not start a mission."); return false; }
    if (IsWorkerRunning()) { Status = TEXT("A worker already owns this route."); return false; }
    for (TActorIterator<ADroneCaptureRoute> It(GetWorld()); It; ++It) if (*It != this && It->IsWorkerRunning()) { Status = TEXT("Another route currently owns the worker."); return false; }
    if (ValidateRoute() != TEXT("Valid")) return false;
    const FString Python = Full(PythonExecutable);
    const FString Script = FPaths::Combine(IPluginManager::Get().FindPlugin(TEXT("AirSimRouteCapture"))->GetBaseDir(), TEXT("Scripts/route_capture.py"));
    if (!FPaths::FileExists(Python) || !FPaths::FileExists(Script)) { Status = TEXT("Worker Python executable or script is missing."); return false; }
    FString Error; auto Mission = MakeMission(Error); if (!Mission) { Status = Error; return false; }
    const FString RunId = FDateTime::UtcNow().ToString(TEXT("%Y%m%dT%H%M%S")) + TEXT("_") + FGuid::NewGuid().ToString(EGuidFormats::Digits);
    RunDirectory = FPaths::Combine(Full(OutputRoot), RouteId + TEXT("_") + RunId);
    if (!IFileManager::Get().MakeDirectory(*RunDirectory, true) || !Save(FPaths::Combine(RunDirectory, TEXT("authored_input.json")), Mission)) { Status=TEXT("Cannot create mission snapshot/output."); return false; }
    if (!ValidateWithWorker(Python,Script,FPaths::Combine(RunDirectory,TEXT("authored_input.json")),Error) || !WriteContext(Mission,Error)) { Status=Error; return false; }
    if (Worker.IsValid()) { FPlatformProcess::CloseProc(Worker); Worker.Reset(); }
    // File paths are quoted; no shell or arbitrary-code IPC is used.
    const FString Args = FString::Printf(TEXT("\"%s\" --mission \"%s\" --run-dir \"%s\" --context \"%s\""), *Script, *FPaths::Combine(RunDirectory,TEXT("authored_input.json")), *RunDirectory, *FPaths::Combine(RunDirectory,TEXT("context.json")));
    LastStatusTime = WorkerStartTime = FPlatformTime::Seconds(); bWatchdogSentStop = false; bRecoveryAttempted=false; LastWorkerStatus.Empty(); LastWorkerState.Empty();
    FRouteCaptureBridge::HideMarkersFromDroneCameras(GetWorld());
    Supervise(0); // Publish clock before the worker's first read.
    Worker = FPlatformProcess::CreateProc(*Python, *Args, false, true, true, nullptr, 0, *FPaths::ProjectDir(), nullptr);
    if (!Worker.IsValid()) { Status = TEXT("Could not start Python worker."); return false; }
    Status = TEXT("Starting worker"); return true;
}
void ADroneCaptureRoute::SendControl(const FString& Command)
{
    if (RunDirectory.IsEmpty()) return;
    auto O = Obj(); O->SetStringField(TEXT("schema_version"), TEXT("1.0.0")); O->SetNumberField(TEXT("id"), ++CommandId); O->SetStringField(TEXT("command"), Command);
    if (!Save(FPaths::Combine(RunDirectory, TEXT("control.json")), O)) Status = TEXT("Could not write worker command.");
}
void ADroneCaptureRoute::Pause() { SendControl(TEXT("pause")); }
void ADroneCaptureRoute::Resume() { SendControl(TEXT("resume")); }
void ADroneCaptureRoute::StopHover()
{
    if (IsWorkerRunning()) SendControl(TEXT("stop"));
    else { bRecoveryAttempted=false; LaunchRecovery(); }
}
void ADroneCaptureRoute::Land()
{
    if (IsWorkerRunning()) SendControl(TEXT("land"));
    else { bRecoveryAttempted=false; LaunchRecovery(true); }
}
void ADroneCaptureRoute::OpenOutputFolder() { FPlatformProcess::ExploreFolder(*(RunDirectory.IsEmpty() ? Full(OutputRoot) : RunDirectory)); }
bool ADroneCaptureRoute::LaunchRecovery(bool bLand)
{
    if (bRecoveryAttempted || RunDirectory.IsEmpty()) return false;
    bRecoveryAttempted=true; bRecoveryLanding=bLand;
    const FString Script=FPaths::Combine(IPluginManager::Get().FindPlugin(TEXT("AirSimRouteCapture"))->GetBaseDir(),TEXT("Scripts/route_capture.py"));
    const FString Args=FString::Printf(TEXT("\"%s\" --mission \"%s\" --run-dir \"%s\" --context \"%s\" --recover %s"),*Script,*FPaths::Combine(RunDirectory,TEXT("authored_input.json")),*RunDirectory,*FPaths::Combine(RunDirectory,TEXT("context.json")),bLand ? TEXT("land") : TEXT("hover"));
    Worker=FPlatformProcess::CreateProc(*Full(PythonExecutable),*Args,false,true,true,nullptr,0,*FPaths::ProjectDir(),nullptr);
    LastStatusTime=FPlatformTime::Seconds(); Status=Worker.IsValid() ? (bLand ? TEXT("Independent landing: validating descent and requesting Land Here.") : TEXT("Independent recovery: requesting cancel/unpause/hover.")) : TEXT("Could not launch independent recovery.");
    return Worker.IsValid();
}
bool ADroneCaptureRoute::Supervise(float Delta)
{
    if (RunDirectory.IsEmpty() || !GetWorld() || !GetWorld()->IsGameWorld()) return true;
    FRouteCaptureVehicleContext C; FString Error;
    if (!FRouteCaptureBridge::Resolve(GetWorld(), VehicleName, CameraName, C, Error)) return true;
    auto Clock = Obj(); Clock->SetStringField(TEXT("schema_version"), TEXT("1.0.0")); Clock->SetNumberField(TEXT("simulation_time_s"), C.SimulationSeconds); Clock->SetObjectField(TEXT("world_origin_ue_cm"), Vec(FVector(C.WorldOrigin))); Clock->SetBoolField(TEXT("paused"), C.Paused); Clock->SetBoolField(TEXT("world_origin_valid"), C.WorldOrigin == InitialWorldOrigin); Clock->SetStringField(TEXT("wall_utc"), FDateTime::UtcNow().ToIso8601());
    FVector Ned; FRouteCaptureBridge::ToLocalNed(GetWorld(), VehicleName, C.BodyPosition, Ned, Error);
    FCollisionQueryParams Query(SCENE_QUERY_STAT(RouteCaptureLanding), false); Query.AddIgnoredActor(C.Pawn.Get());
    // Authored markers have collision disabled. Tagged observer proxies are also
    // excluded from sweeps once, during the immutable native start snapshot.
    for (const auto& Marker:SnapshotMarkerActors) if (Marker.IsValid()) Query.AddIgnoredActor(Marker.Get());
    FHitResult Ground;
    const bool Hit = GetWorld()->SweepSingleByChannel(Ground, C.BodyPosition, C.BodyPosition-FVector(0,0,100*C.WorldToMeters), FQuat::Identity, ECC_WorldStatic, FCollisionShape::MakeSphere(SnapshotClearanceM*C.WorldToMeters), Query);
    auto Landing = Obj(); Landing->SetObjectField(TEXT("position_ned_m"), Vec(Ned)); Landing->SetNumberField(TEXT("tolerance_m"), .5); Landing->SetNumberField(TEXT("clearance_m"), SnapshotClearanceM); Landing->SetBoolField(TEXT("clear"), Hit && !Ground.bStartPenetrating && Ground.ImpactNormal.Z >= .7); Landing->SetObjectField(TEXT("ground_position_ue_cm"), Vec(Ground.ImpactPoint)); Landing->SetStringField(TEXT("ground_actor_name"),Hit ? GetNameSafe(Ground.GetActor()) : FString()); Clock->SetObjectField(TEXT("landing_validation"), Landing);
    Save(FPaths::Combine(RunDirectory, TEXT("clock.json")), Clock);
    if (C.WorldOrigin != InitialWorldOrigin && IsWorkerRunning()) { SendControl(TEXT("stop")); Status = TEXT("World origin changed: stopping mission."); }
    FString StatusText; FObject WorkerStatus;
    if (LoadShared(FPaths::Combine(RunDirectory, TEXT("status.json")), StatusText) && Parse(StatusText, WorkerStatus)) {
        if (StatusText != LastWorkerStatus) { LastStatusTime = FPlatformTime::Seconds(); LastWorkerStatus = StatusText; }
        FString State, Message; WorkerStatus->TryGetStringField(TEXT("state"), State); WorkerStatus->TryGetStringField(TEXT("message"), Message); LastWorkerState=State;
        double Pairs = 0; WorkerStatus->TryGetNumberField(TEXT("pairs"), Pairs);
        double Nodes=0; WorkerStatus->TryGetNumberField(TEXT("nodes_completed"),Nodes); int32 Total=0; for (ADroneRoutePoint* P:OrderedPoints) if (IsValid(P)&&P->bEnabled) ++Total;
        // After an independent helper is reaped below, its acknowledged/failed
        // result is authoritative. The mission file may retain "landing" forever;
        // continue reading its heartbeat without replacing that terminal result.
        if (!bRecoveryAttempted || Worker.IsValid()) Status = FString::Printf(TEXT("%s | node %d/%d | %d pairs | %s"), *State, int32(Nodes),Total,int32(Pairs), *Message);
    }
    if (IsWorkerRunning() && FPlatformTime::Seconds()-LastStatusTime > 30 && !bWatchdogSentStop) { SendControl(TEXT("stop")); bWatchdogSentStop = true; Status = TEXT("Worker heartbeat stale: requesting stop/hover."); }
    if (IsWorkerRunning() && FPlatformTime::Seconds()-LastStatusTime > 45) {
        FPlatformProcess::TerminateProc(Worker,true); FPlatformProcess::CloseProc(Worker); Worker.Reset();
        auto O=Obj(); O->SetStringField(TEXT("reason"),TEXT("Worker heartbeat timeout")); O->SetBoolField(TEXT("recovery_acknowledged"),false); Save(FPaths::Combine(RunDirectory,TEXT("native_supervisor.json")),O);
        LaunchRecovery();
    }
    if (Worker.IsValid() && !IsWorkerRunning()) {
        int32 Code = -1; FPlatformProcess::GetProcReturnCode(Worker, &Code); FPlatformProcess::CloseProc(Worker); Worker.Reset();
        if (bRecoveryAttempted) {
            auto O=Obj(); O->SetStringField(TEXT("reason"),TEXT("Independent recovery completed")); O->SetBoolField(TEXT("recovery_acknowledged"),Code==0); O->SetNumberField(TEXT("recovery_exit_code"),Code); Save(FPaths::Combine(RunDirectory,TEXT("native_supervisor.json")),O);
            Status=Code==0 ? (bRecoveryLanding ? TEXT("Landing acknowledged; API control released.") : TEXT("Independent recovery acknowledged hover; API control retained.")) : TEXT("Independent recovery failed; requested action was not acknowledged.");
        }
        else if (Code != 0 || (LastWorkerState!=TEXT("completed") && LastWorkerState!=TEXT("stopped") && LastWorkerState!=TEXT("limit_reached"))) { Status = FString::Printf(TEXT("Worker exited (%d). Starting independent hover recovery."), Code); LaunchRecovery(); }
    }
    return true;
}

#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Misc/ScopeExit.h"
#include "Async/Async.h"
#include <atomic>
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRouteAtomicPublicationTest,"AirSim.RouteCapture.AtomicPublication",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FRouteAtomicPublicationTest::RunTest(const FString&)
{
    const FString Folder=FPaths::Combine(FPaths::ProjectSavedDir(),TEXT("RouteCaptureTests"),FGuid::NewGuid().ToString(EGuidFormats::Digits));
    const FString Path=FPaths::ConvertRelativePathToFull(FPaths::Combine(Folder,TEXT("clock.json")));
    auto Snapshot=Obj(); Snapshot->SetNumberField(TEXT("generation"),0); Snapshot->SetStringField(TEXT("payload"),FString::ChrN(4096,TEXT('x')));
    if (!TestTrue(TEXT("Initial snapshot published"),Save(Path,Snapshot))) return false;
#if PLATFORM_WINDOWS
    HANDLE Locked=::CreateFileW(*Path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    if (TestTrue(TEXT("Deny-delete reader opened"),Locked!=INVALID_HANDLE_VALUE)) {
        Snapshot->SetNumberField(TEXT("generation"),1);
        uint32 Error=0;
        TestTrue(TEXT("Deny-delete reader causes a bounded deferral"),Publish(Path,Snapshot,&Error)==EPublicationResult::Deferred);
        TestTrue(TEXT("Deferral reports a Windows sharing/access error"),Error==ERROR_SHARING_VIOLATION || Error==ERROR_LOCK_VIOLATION || Error==ERROR_ACCESS_DENIED);
        ::CloseHandle(Locked);
        FString Text; FObject Old;
        TestTrue(TEXT("Old snapshot remains readable after failed replacement"),LoadShared(Path,Text)&&Parse(Text,Old));
        if (Old) TestEqual(TEXT("Old generation remains published"),Old->GetIntegerField(TEXT("generation")),0);
    }
#endif
    auto PublishEventually=[&](double Deadline) {
        EPublicationResult Result;
        do {
            Result=Publish(Path,Snapshot);
            if (Result==EPublicationResult::Deferred) FPlatformProcess::SleepNoStats(.005f);
        } while (Result==EPublicationResult::Deferred && FPlatformTime::Seconds()<Deadline);
        return Result==EPublicationResult::Published;
    };
    TestTrue(TEXT("Publication resumes after the denying reader closes"),PublishEventually(FPlatformTime::Seconds()+1));
    std::atomic<bool> Reading(true); std::atomic<int32> Failures(0); std::atomic<int32> Reads(0);
    auto Reader=Async(EAsyncExecution::Thread,[&] {
        int32 PreviousGeneration=0;
        while (Reading.load()) {
            FString Text, Payload; FObject Current; double Generation=0;
            if (!LoadShared(Path,Text) || !Parse(Text,Current) || !Current->TryGetStringField(TEXT("payload"),Payload) || Payload.Len()!=4096 || !Current->TryGetNumberField(TEXT("generation"),Generation) || Generation<PreviousGeneration || Generation>200) ++Failures;
            else PreviousGeneration=int32(Generation);
            ++Reads;
        }
    });
    int32 Published=0, Deferred=0, HardFailures=0; uint32 LastError=0;
    double LastPublication=FPlatformTime::Seconds(), LongestPublicationGap=0;
    for (int32 Generation=1; Generation<=200; ++Generation) {
        Snapshot->SetNumberField(TEXT("generation"),Generation);
        const auto Result=Publish(Path,Snapshot,&LastError);
        const double Now=FPlatformTime::Seconds();
        LongestPublicationGap=FMath::Max(LongestPublicationGap,Now-LastPublication);
        if (Result==EPublicationResult::Published) { ++Published; LastPublication=Now; }
        else if (Result==EPublicationResult::Deferred) ++Deferred;
        else ++HardFailures;
    }
    Reading.store(false); Reader.Wait();
    AddInfo(FString::Printf(TEXT("Atomic publication stress: %d published, %d deferred, %d hard failures, %d reads, longest publication gap %.3fs, last system error %u"),Published,Deferred,HardFailures,Reads.load(),LongestPublicationGap,LastError));
    TestEqual(TEXT("Concurrent publication has no non-transient failures"),HardFailures,0);
    TestTrue(TEXT("Publication progresses while the shared reader is active"),Published>0);
    TestTrue(TEXT("Publication freshness stays below the 3-second worker watchdog"),LongestPublicationGap<2);
    TestTrue(TEXT("Reader overlapped publication"),Reads.load()>0);
    TestEqual(TEXT("Concurrent reader sees only complete, present, monotonic snapshots"),Failures.load(),0);
    TestTrue(TEXT("Latest deferred generation eventually publishes"),PublishEventually(FPlatformTime::Seconds()+1));
    FString FinalText; FObject Final;
    TestTrue(TEXT("Final publication remains readable"),LoadShared(Path,FinalText)&&Parse(FinalText,Final));
    if (Final) TestEqual(TEXT("Exact latest generation is committed after contention"),Final->GetIntegerField(TEXT("generation")),200);
    IFileManager::Get().Delete(*Path,false,true); IFileManager::Get().DeleteDirectory(*Folder,false,false);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRouteSettingsRoundTripTest,"AirSim.RouteCapture.SettingsRoundTrip",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FRouteSettingsRoundTripTest::RunTest(const FString&)
{
    FRouteNodeSettings Node; Node.Capture=ERouteNodeCapture::Burst; Node.BurstCount=7; Node.BurstIntervalMs=100; Node.DelayMs=200;
    FRouteNodeSettings Reloaded; ReadNode(NodeJson(Node),Reloaded);
    TestEqual(TEXT("Finite burst count persists"),Reloaded.BurstCount,7); TestEqual(TEXT("Burst cadence persists"),Reloaded.BurstIntervalMs,100); TestEqual(TEXT("Delay persists"),Reloaded.DelayMs,200);
    FRouteSegmentSettings Segment; Segment.SpeedMps=1.5f; Segment.Capture=ERouteTravelCapture::TimeInterval; Segment.IntervalMs=100;
    FRouteSegmentSettings ReloadedSegment; ReadSegment(SegmentJson(Segment),ReloadedSegment);
    TestEqual(TEXT("Explicit segment speed persists"),ReloadedSegment.SpeedMps,1.5f); TestEqual(TEXT("100 ms cadence persists"),ReloadedSegment.IntervalMs,100);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRouteCaptureReplacementTest,"AirSim.RouteCapture.CaptureReplacement",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FRouteCaptureReplacementTest::RunTest(const FString&)
{
    auto Base=SegmentJson(FRouteSegmentSettings()); auto Override=Obj(); auto Capture=Obj(); Capture->SetStringField(TEXT("mode"),TEXT("distance_interval")); Capture->SetNumberField(TEXT("interval_m"),.5); Override->SetObjectField(TEXT("capture"),Capture);
    auto Result=Merged(Base,Override); auto Actual=Result->GetObjectField(TEXT("capture"));
    TestFalse(TEXT("Capture replacement discards inherited time cadence"),Actual->HasField(TEXT("interval_ms"))); TestEqual(TEXT("Distance interval retained"),Actual->GetNumberField(TEXT("interval_m")),.5);
    TestTrue(TEXT("Resolved segment is valid"),SegmentShape(Result));
    FRouteNodeSettings Fly; Fly.bFlyThrough=true;
    TestFalse(TEXT("Fly-through cannot capture/settle"),ValidNode(Fly)); Fly.Capture=ERouteNodeCapture::Off; Fly.SettleTimeMs=0;
    TestTrue(TEXT("Travel-only fly-through accepted"),ValidNode(Fly));
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRouteImportContractTest,"AirSim.RouteCapture.ImportContract",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FRouteImportContractTest::RunTest(const FString&)
{
    FString Source; FObject Mission;
    const FString Path=FPaths::Combine(IPluginManager::Get().FindPlugin(TEXT("AirSimRouteCapture"))->GetBaseDir(),TEXT("Content/mission.default.json"));
    if (!TestTrue(TEXT("Default mission loads"),FFileHelper::LoadFileToString(Source,*Path)&&Parse(Source,Mission))) return false;
    TestTrue(TEXT("Versioned default contract accepted"),ImportShape(Mission));
    auto Segments=Mission->GetArrayField(TEXT("segments")); Segments.Swap(0,1); Mission->SetArrayField(TEXT("segments"),Segments);
    TestFalse(TEXT("Out-of-order explicit segments rejected"),ImportShape(Mission));
    Mission->SetStringField(TEXT("schema_version"),TEXT("2.0.0")); TestFalse(TEXT("Unknown version rejected"),ImportShape(Mission));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRouteSegmentIdentityRoundTripTest,"AirSim.RouteCapture.SegmentIdentityRoundTrip",EAutomationTestFlags::EditorContext|EAutomationTestFlags::EngineFilter)
bool FRouteSegmentIdentityRoundTripTest::RunTest(const FString&)
{
    FString Source; FObject Mission;
    const FString Template=FPaths::Combine(IPluginManager::Get().FindPlugin(TEXT("AirSimRouteCapture"))->GetBaseDir(),TEXT("Content/mission.default.json"));
    if (!TestTrue(TEXT("Identity fixture loads"),FFileHelper::LoadFileToString(Source,*Template)&&Parse(Source,Mission))) return false;
    auto Segments=Mission->GetArrayField(TEXT("segments"));
    Segments[0]->AsObject()->SetStringField(TEXT("id"),TEXT("InspectionEdge_Custom17"));
    Segments[1]->AsObject()->SetStringField(TEXT("id"),TEXT("InheritedEdge_Custom29"));
    Segments[1]->AsObject()->RemoveField(TEXT("settings"));
    const FString Folder=FPaths::Combine(FPaths::ProjectSavedDir(),TEXT("RouteCaptureTests"),FGuid::NewGuid().ToString(EGuidFormats::Digits));
    const FString Input=FPaths::ConvertRelativePathToFull(FPaths::Combine(Folder,TEXT("input.json")));
    const FString Output=FPaths::ConvertRelativePathToFull(FPaths::Combine(Folder,TEXT("output.json")));
    UWorld* World=nullptr;
    ON_SCOPE_EXIT {
        if (World) World->DestroyWorld(false);
        IFileManager::Get().Delete(*Input,false,true); IFileManager::Get().Delete(*Output,false,true); IFileManager::Get().DeleteDirectory(*Folder,false,false);
    };
    if (!TestTrue(TEXT("Identity fixture published"),Save(Input,Mission))) return false;
    World=UWorld::CreateWorld(EWorldType::Game,false);
    if (!TestNotNull(TEXT("Isolated authoring world created"),World)) return false;
    auto* Route=World->SpawnActor<ADroneCaptureRoute>();
    if (!TestNotNull(TEXT("Route spawned"),Route)) return false;
    Route->JsonFile=Input;
    if (!TestTrue(TEXT("Native strict import succeeds"),Route->ImportMission())) { AddError(Route->Status); return false; }
    if (!TestEqual(TEXT("Three authored points imported"),Route->OrderedPoints.Num(),3)) return false;
    TestEqual(TEXT("Identity-only segments are retained"),Route->SegmentOverrides.Num(),2);
    ADroneRoutePoint* A=Route->OrderedPoints[0]; ADroneRoutePoint* B=Route->OrderedPoints[1]; ADroneRoutePoint* C=Route->OrderedPoints[2];
    Route->JsonFile=Output; FObject Exported;
    auto Export=[&] { FString Text; return Route->ExportMission()&&LoadShared(Output,Text)&&Parse(Text,Exported); };
    if (!TestTrue(TEXT("Native export succeeds"),Export())) { AddError(Route->Status); return false; }
    TestEqual(TEXT("Arbitrary segment ID round-trips"),Exported->GetArrayField(TEXT("segments"))[0]->AsObject()->GetStringField(TEXT("id")),FString(TEXT("InspectionEdge_Custom17")));
    TestEqual(TEXT("Inherited segment ID round-trips"),Exported->GetArrayField(TEXT("segments"))[1]->AsObject()->GetStringField(TEXT("id")),FString(TEXT("InheritedEdge_Custom29")));
    TestFalse(TEXT("Identity-only edge still inherits defaults"),Exported->GetArrayField(TEXT("segments"))[1]->AsObject()->HasField(TEXT("settings")));
    Route->OrderedPoints={C,A,B}; Route->RefreshPreview();
    if (!TestTrue(TEXT("Reordered route exports"),Export())) return false;
    const auto Preserved=Exported->GetArrayField(TEXT("segments"))[1]->AsObject();
    TestEqual(TEXT("Custom ID follows its endpoints after reorder"),Preserved->GetStringField(TEXT("id")),FString(TEXT("InspectionEdge_Custom17")));
    TestEqual(TEXT("Override remains on original source"),Preserved->GetStringField(TEXT("from")),A->PointId);
    TestEqual(TEXT("Override remains on original destination"),Preserved->GetStringField(TEXT("to")),B->PointId);
    TestEqual(TEXT("Override speed survives reorder"),Preserved->GetObjectField(TEXT("settings"))->GetNumberField(TEXT("speed_mps")),1.0);
    const FString NewEdgeId=Exported->GetArrayField(TEXT("segments"))[0]->AsObject()->GetStringField(TEXT("id"));
    Route->OrderedPoints={B,C,A}; Route->RefreshPreview();
    if (!TestTrue(TEXT("Same new edge exports at another sequence position"),Export())) return false;
    TestEqual(TEXT("Generated ID is independent of sequence position"),Exported->GetArrayField(TEXT("segments"))[1]->AsObject()->GetStringField(TEXT("id")),NewEdgeId);
    const FString LongId=GeneratedSegmentId(FString::ChrN(80,TEXT('A')),FString::ChrN(80,TEXT('B')));
    TestTrue(TEXT("Long endpoint IDs produce a bounded schema-valid segment ID"),LongId.Len()<=80&&ValidId(LongId));
    TestNotEqual(TEXT("Directed endpoints have distinct generated identities"),GeneratedSegmentId(TEXT("A"),TEXT("B")),GeneratedSegmentId(TEXT("B"),TEXT("A")));
    return true;
}
#endif

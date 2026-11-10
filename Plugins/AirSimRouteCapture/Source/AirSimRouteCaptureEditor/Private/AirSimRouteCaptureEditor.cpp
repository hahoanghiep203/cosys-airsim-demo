#include "Modules/ModuleManager.h"
#include "DroneCaptureRoute.h"
#include "Editor.h"
#include "Engine/Selection.h"
#include "EngineUtils.h"
#include "ToolMenus.h"
#include "ScopedTransaction.h"
#include "PropertyEditorModule.h"
#include "IDetailsView.h"
#include "Widgets/Docking/SDockTab.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SSpinBox.h"
#include "Widgets/Text/STextBlock.h"
#include "Framework/Docking/TabManager.h"

static const FName RouteTab(TEXT("DroneRouteCapture"));

class SDroneRouteCapturePanel : public SCompoundWidget
{
public:
    SLATE_BEGIN_ARGS(SDroneRouteCapturePanel) {} SLATE_END_ARGS()
    void Construct(const FArguments&)
    {
        FDetailsViewArgs Args; Args.bHideSelectionTip = true;
        Details = FModuleManager::LoadModuleChecked<FPropertyEditorModule>(TEXT("PropertyEditor")).CreateDetailView(Args);
        auto Buttons = SNew(SVerticalBox);
        auto Row = [&Buttons](const TSharedRef<SWidget>& A, const TSharedRef<SWidget>& B) { Buttons->AddSlot().AutoHeight().Padding(2)[SNew(SHorizontalBox) + SHorizontalBox::Slot().FillWidth(1)[A] + SHorizontalBox::Slot().FillWidth(1)[B]]; };
        Row(Button(TEXT("Create route"), [this] { CreateRoute(); }), Button(TEXT("Use selected route"), [this] { UseSelection(); }));
        Row(Button(TEXT("Add point"), [this] { AddPoint(false); }), Button(TEXT("Create point at selection"), [this] { AddPoint(true); }));
        Row(Button(TEXT("Move point up"), [this] { Reorder(-1); }), Button(TEXT("Move point down"), [this] { Reorder(1); }));
        Row(Button(TEXT("Select point"), [this] { SelectPoint(); }), Button(TEXT("Remove point from route"), [this] { RemovePoint(); }));
        Buttons->AddSlot().AutoHeight().Padding(2)[SNew(SHorizontalBox) + SHorizontalBox::Slot().AutoWidth()[SNew(STextBlock).Text(FText::FromString(TEXT("Point number: ")))] + SHorizontalBox::Slot()[SNew(SSpinBox<int32>).MinValue(1).Value_Lambda([this] { return PointIndex+1; }).OnValueChanged_Lambda([this](int32 Value) { PointIndex = Value-1; })]];
        Buttons->AddSlot().AutoHeight().Padding(4)[SNew(STextBlock).Text_Lambda([this] { FString Text; if (Route.IsValid()) { int32 I=0; for (ADroneRoutePoint* P : Route->OrderedPoints) Text += FString::Printf(TEXT("%02d  %s%s\n"), ++I, IsValid(P) ? *P->PointLabel : TEXT("MISSING"), IsValid(P) && !P->bEnabled ? TEXT(" (disabled)") : TEXT("")); } return FText::FromString(Text); })];
        Row(Button(TEXT("Import JSON"), [this] { if (Route.IsValid()) { FScopedTransaction T(FText::FromString(TEXT("Import drone route"))); Route->ImportMission(); } }), Button(TEXT("Export JSON"), [this] { if (Route.IsValid()) Route->ExportMission(); }));
        Row(Button(TEXT("Waypoint defaults"), [this] { ApplyPreset(0); }), Button(TEXT("Travel defaults"), [this] { ApplyPreset(1); }));
        Row(Button(TEXT("Both defaults"), [this] { ApplyPreset(2); }), SNew(STextBlock).AutoWrapText(true).Text(FText::FromString(TEXT("Point and segment overrides retain their settings."))));
        Row(Button(TEXT("Validate route"), [this] { if (Route.IsValid()) Route->ValidateRoute(); }), Button(TEXT("Start (in Play)"), [this] { if (auto* R = PlayRoute()) R->Start(); }));
        Row(Button(TEXT("Pause"), [this] { if (auto* R = PlayRoute()) R->Pause(); }), Button(TEXT("Resume"), [this] { if (auto* R = PlayRoute()) R->Resume(); }));
        Row(Button(TEXT("Stop and Hover"), [this] { if (auto* R = PlayRoute()) R->StopHover(); }), Button(TEXT("Land Here"), [this] { if (auto* R = PlayRoute()) R->Land(); }));
        Row(Button(TEXT("Refresh route preview"), [this] { if (Route.IsValid()) Route->RefreshPreview(); }), Button(TEXT("Open output folder"), [this] { if (auto* R = PlayRoute()) R->OpenOutputFolder(); else if (Route.IsValid()) Route->OpenOutputFolder(); }));
        Buttons->AddSlot().AutoHeight().Padding(4)[SNew(STextBlock).AutoWrapText(true).Text_Lambda([this] { auto* R = PlayRoute(); return FText::FromString(R ? R->Status : Route.IsValid() ? Route->Status : TEXT("Create or select a Drone Capture Route.")); })];
        ChildSlot[SNew(SScrollBox) + SScrollBox::Slot()[SNew(SVerticalBox) + SVerticalBox::Slot().AutoHeight()[Buttons] + SVerticalBox::Slot().AutoHeight()[SNew(STextBlock).AutoWrapText(true).Text(FText::FromString(TEXT("Edit route defaults, explicit segment overrides, camera, output and JSON path below. Select a point to edit its node settings in the level Details panel. Play alone never starts a mission.")))] + SVerticalBox::Slot().AutoHeight()[SNew(SBox).MinDesiredHeight(500)[Details.ToSharedRef()]]]];
        UseSelection();
    }
private:
    TWeakObjectPtr<ADroneCaptureRoute> Route;
    TSharedPtr<IDetailsView> Details;
    int32 PointIndex = 0;
    TSharedRef<SWidget> Button(const FString& Label, TFunction<void()> Action)
    {
        return SNew(SButton).Text(FText::FromString(Label)).OnClicked_Lambda([Action] { Action(); return FReply::Handled(); });
    }
    UWorld* EditorWorld() const { return GEditor ? GEditor->GetEditorWorldContext().World() : nullptr; }
    ADroneCaptureRoute* PlayRoute() const
    {
        if (!GEditor || !GEditor->PlayWorld || !Route.IsValid()) return nullptr;
        for (TActorIterator<ADroneCaptureRoute> It(GEditor->PlayWorld); It; ++It) if (It->RouteId == Route->RouteId) return *It;
        return nullptr;
    }
    void UseSelection()
    {
        if (!GEditor) return;
        for (FSelectionIterator It(*GEditor->GetSelectedActors()); It; ++It) if (auto* R = Cast<ADroneCaptureRoute>(*It)) { Route = R; Details->SetObject(R); return; }
        if (!Route.IsValid() && EditorWorld()) for (TActorIterator<ADroneCaptureRoute> It(EditorWorld()); It; ++It) { Route = *It; Details->SetObject(*It); return; }
    }
    void CreateRoute()
    {
        if (!EditorWorld() || GEditor->PlayWorld) return;
        FScopedTransaction T(FText::FromString(TEXT("Create drone route")));
        Route = EditorWorld()->SpawnActor<ADroneCaptureRoute>(); Route->SetFlags(RF_Transactional); Details->SetObject(Route.Get());
        GEditor->SelectNone(false, true); GEditor->SelectActor(Route.Get(), true, true); Route->MarkPackageDirty();
    }
    void AddPoint(bool AtSelection)
    {
        if (!Route.IsValid() || GEditor->PlayWorld) return;
        FTransform Transform = Route->GetActorTransform();
        if (AtSelection) { if (auto* A = Cast<AActor>(GEditor->GetSelectedActors()->GetTop(AActor::StaticClass()))) Transform = A->GetActorTransform(); }
        else if (!Route->OrderedPoints.IsEmpty() && IsValid(Route->OrderedPoints.Last())) { Transform = Route->OrderedPoints.Last()->GetActorTransform(); Transform.AddToTranslation(FVector(200,0,0)); }
        FScopedTransaction T(FText::FromString(TEXT("Add drone route point"))); Route->Modify();
        auto* P = EditorWorld()->SpawnActor<ADroneRoutePoint>(Transform.GetLocation(), Transform.Rotator()); P->SetFlags(RF_Transactional); P->PointLabel = FString::Printf(TEXT("View %d"), Route->OrderedPoints.Num()+1); Route->OrderedPoints.Add(P); PointIndex = Route->OrderedPoints.Num()-1; Route->RefreshPreview(); Route->MarkPackageDirty(); SelectPoint();
    }
    void Reorder(int32 Delta)
    {
        if (!Route.IsValid() || GEditor->PlayWorld || !Route->OrderedPoints.IsValidIndex(PointIndex) || !Route->OrderedPoints.IsValidIndex(PointIndex+Delta)) return;
        FScopedTransaction T(FText::FromString(TEXT("Reorder drone route point"))); Route->Modify(); Route->OrderedPoints.Swap(PointIndex, PointIndex+Delta); PointIndex += Delta; Route->RefreshPreview(); Route->MarkPackageDirty();
    }
    void SelectPoint()
    {
        if (!Route.IsValid() || !Route->OrderedPoints.IsValidIndex(PointIndex)) return;
        GEditor->SelectNone(false, true); GEditor->SelectActor(Route->OrderedPoints[PointIndex], true, true);
    }
    void RemovePoint()
    {
        if (!Route.IsValid() || GEditor->PlayWorld || !Route->OrderedPoints.IsValidIndex(PointIndex)) return;
        FScopedTransaction T(FText::FromString(TEXT("Remove drone route point"))); Route->Modify(); Route->OrderedPoints.RemoveAt(PointIndex); PointIndex = FMath::Max(0, PointIndex-1); Route->RefreshPreview(); Route->MarkPackageDirty();
    }
    void ApplyPreset(int32 Mode)
    {
        if (!Route.IsValid() || GEditor->PlayWorld) return;
        FScopedTransaction T(FText::FromString(TEXT("Change route capture defaults"))); Route->Modify();
        Route->DefaultNode.bFlyThrough=Mode==1; Route->DefaultNode.Capture=Mode==1 ? ERouteNodeCapture::Off : ERouteNodeCapture::Single;
        Route->DefaultNode.SettleTimeMs=Mode==1 ? 0 : 500; Route->DefaultNode.ExtraHoldMs=0;
        if (Mode==0) Route->DefaultSegment.Capture=ERouteTravelCapture::Off;
        else if (Route->DefaultSegment.Capture==ERouteTravelCapture::Off) Route->DefaultSegment.Capture=ERouteTravelCapture::TimeInterval;
        Route->MarkPackageDirty(); Route->ValidateRoute();
    }
};

class FAirSimRouteCaptureEditorModule : public IModuleInterface
{
    FTSTicker::FDelegateHandle PreviewTick;
public:
    virtual void StartupModule() override
    {
        FGlobalTabmanager::Get()->RegisterNomadTabSpawner(RouteTab, FOnSpawnTab::CreateLambda([](const FSpawnTabArgs&) { return SNew(SDockTab).TabRole(ETabRole::NomadTab)[SNew(SDroneRouteCapturePanel)]; })).SetDisplayName(FText::FromString(TEXT("Drone Route Capture"))).SetMenuType(ETabSpawnerMenuType::Hidden);
        UToolMenus::RegisterStartupCallback(FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FAirSimRouteCaptureEditorModule::RegisterMenu));
        PreviewTick = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateLambda([](float) { if (GEditor && !GEditor->PlayWorld) { if (auto* W = GEditor->GetEditorWorldContext().World()) for (TActorIterator<ADroneCaptureRoute> It(W); It; ++It) It->RefreshPreview(); } return true; }), .25f);
    }
    void RegisterMenu()
    {
        FToolMenuOwnerScoped Owner(this); auto* Menu = UToolMenus::Get()->ExtendMenu(TEXT("LevelEditor.MainMenu.Window"));
        Menu->FindOrAddSection(TEXT("AirSim")).AddMenuEntry(TEXT("OpenDroneRouteCapture"), FText::FromString(TEXT("Drone Route Capture")), FText::FromString(TEXT("Author and run ordered RGB + ThermalIR routes.")), FSlateIcon(), FUIAction(FExecuteAction::CreateLambda([] { FGlobalTabmanager::Get()->TryInvokeTab(RouteTab); })));
    }
    virtual void ShutdownModule() override
    {
        FTSTicker::GetCoreTicker().RemoveTicker(PreviewTick); UToolMenus::UnRegisterStartupCallback(this); UToolMenus::UnregisterOwner(this); FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(RouteTab);
    }
};
IMPLEMENT_MODULE(FAirSimRouteCaptureEditorModule, AirSimRouteCaptureEditor)

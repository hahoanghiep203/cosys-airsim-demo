#pragma once

#include "CoreMinimal.h"

// Plain value data shared by the game/render threads. No UObject references.
// These layouts are mirrored in ThermalPreview.usf.
struct FThermalGpuSample
{
    FVector4f PositionMaterial;
    FVector4f Normal;
};
struct FThermalGpuCell
{
    FIntVector4 Key; // receiver index, local cell X/Y/Z
    FUintVector4 Range; // first sample, sample count, unused, unused
};
struct FThermalGpuCellRange { uint32 First = 0, Count = 0; };
struct FThermalGpuGrid { FIntVector4 MinOffset; FIntVector4 Size; };
struct FThermalGpuReceiver
{
    FMatrix44f LocalToWorld;
    FMatrix44f WorldToLocal;
    FMatrix44f NormalToWorld;
    FVector4f BoundsMinSpacing;
    FVector4f BoundsMax;
    FVector4f ActiveMin;
    FVector4f ActiveMax;
    FIntVector4 CellMinOffset;
    FIntVector4 CellSize;
};
struct FThermalGpuUniformSurface
{
    FVector4f MinTemperature;
    FVector4f MaxEmissivity;
};
struct FThermalGpuProfile
{
    FUintVector4 Identity; // color key, candidate offset/count, unused
    FVector4f Values; // temperature K, emissivity, unused, unused
};
struct FThermalGpuTopology
{
    uint64 Revision = 0;
    TArray<FThermalGpuSample> Samples;
    TArray<FThermalGpuCellRange> Cells;
    TArray<FThermalGpuGrid> Grids;
};
struct FThermalGpuTemperatures
{
    uint64 Revision = 0;
    TArray<FVector2f> Values;
    TArray<FBox> ActiveBounds;
};
struct FThermalGpuFrame
{
    TSharedPtr<const FThermalGpuTopology, ESPMode::ThreadSafe> Topology;
    TSharedPtr<const FThermalGpuTemperatures, ESPMode::ThreadSafe> Temperatures;
    TArray<FThermalGpuReceiver> Receivers;
    TArray<FThermalGpuUniformSurface> UniformSurfaces;
    TMap<uint32, TArray<uint32>> ReceiversByColor;
};

namespace ThermalGpuData
{
inline int32 DenseCellIndex(const FThermalGpuGrid& G, const FIntVector& K)
{
    const FIntVector P(K.X - G.MinOffset.X, K.Y - G.MinOffset.Y, K.Z - G.MinOffset.Z);
    if (P.X < 0 || P.Y < 0 || P.Z < 0 || P.X >= G.Size.X || P.Y >= G.Size.Y || P.Z >= G.Size.Z) return INDEX_NONE;
    return G.MinOffset.W + (P.Z * G.Size.Y + P.Y) * G.Size.X + P.X;
}
inline uint32 HashCell(const FIntVector4& K)
{
    // Unsigned arithmetic must match HLSL, including negative cell coordinates.
    uint32 H = uint32(K.X) * 73856093u ^ uint32(K.Y) * 19349663u ^
        uint32(K.Z) * 83492791u ^ uint32(K.W) * 2654435761u;
    H ^= H >> 16; H *= 2246822519u; return H ^ (H >> 13);
}
inline uint32 HashColor(uint32 K)
{
    K ^= K >> 16; K *= 2246822519u; return K ^ (K >> 13);
}
inline void InsertCell(TArray<FThermalGpuCell>& Table, const FIntVector4& Key, uint32 First, uint32 Count)
{
    uint32 Slot = HashCell(Key) & (Table.Num() - 1);
    while (Table[Slot].Range.Y) Slot = (Slot + 1) & (Table.Num() - 1);
    Table[Slot].Key = Key;
    Table[Slot].Range = FUintVector4(First, Count, 0, 0);
}
}

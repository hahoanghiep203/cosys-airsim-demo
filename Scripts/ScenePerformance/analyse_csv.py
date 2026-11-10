"""Summarize engine CSV frames and the cost associated with the longest frame."""
import csv
import json
from pathlib import Path
root=Path(__file__).resolve().parents[2]
reports=[]
for file in sorted((root/'Saved/Profiling/CSV').glob('*.csv')):
    try:
        with file.open('rb') as probe:
            if not probe.read(1):continue
    except PermissionError:continue  # Active profiler capture still owns this file.
    with file.open(newline='',encoding='utf-8-sig') as stream:
        reader=csv.reader(stream)
        header=next(reader)
        columns={name:i for i,name in enumerate(header)}
        rows=[]
        for row in reader:
            if not row or row[0].startswith('[') or row[0]=='EVENTS':continue
            try: rows.append([float(v) if v else 0 for v in row[1:]])
            except ValueError:continue
    if not rows:continue
    def values(name):
        index=columns[name]-1
        return [row[index] for row in rows if len(row)>index]
    summary={}
    for name in header:
        if name not in ('FrameTime','GameThreadTime','RenderThreadTime','GPUFrameTime','GPUTime','GPUMem/LocalUsedMB','GPUMem/LocalBudgetMB','RHI/DrawCalls'):continue
        data=sorted(values(name))
        if not data:continue
        summary[name]={'mean':sum(data)/len(data),'p95':data[int(len(data)*.95)],'p99':data[int(len(data)*.99)],'max':data[-1]}
        if name=='FrameTime':summary[name].update(over_100ms=sum(v>100 for v in data),over_500ms=sum(v>500 for v in data),fps=1000/(sum(data)/len(data)))
    ft=values('FrameTime') if 'FrameTime' in columns else []
    worst=rows[max(range(len(ft)),key=lambda i:ft[i])] if ft else []
    costs=[(name,worst[i-1]) for name,i in columns.items() if i and i-1<len(worst) and (name.startswith('Exclusive/') or name in ('FrameTime','GameThreadTime','RenderThreadTime','GPUFrameTime'))]
    reports.append({'csv':file.name,'frames':len(rows),'summary':summary,'longest_frame_costs':sorted(costs,key=lambda v:-v[1])[:12]})
(root/'Saved/ProjectMaintenance/engine_frame_summary.json').write_text(json.dumps(reports,indent=2))
print(json.dumps(reports,indent=2))

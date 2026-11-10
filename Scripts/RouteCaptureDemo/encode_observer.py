"""Encode actual fixed-camera frames, preserving their simulation-time spacing."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

import cv2
import numpy as np
from build_evidence_report import write_json

def encode(folder, destination, label):
    folder=Path(folder).resolve()
    destination=Path(destination).resolve()
    data=json.loads((folder/'frames.json').read_text(encoding='utf-8'))
    frames=data['frames']
    if len(frames)<2: raise RuntimeError('At least two actual observer frames are required')
    positions=np.asarray([f['position_cm'] for f in frames],dtype=np.float64)
    rotations=np.asarray([f['rotation_deg'] for f in frames],dtype=np.float64)
    position_delta=float(np.linalg.norm(positions-positions[0],axis=1).max())
    rotation_delta=float(np.abs(rotations-rotations[0]).max())
    if position_delta>1e-6 or rotation_delta>1e-6:
        raise RuntimeError('Observer moved or changed angle; refuse fixed-camera evidence')
    durations=[b['sim_time_s']-a['sim_time_s'] for a,b in zip(frames[:-1],frames[1:])]
    if any(not math.isfinite(t) or t<=0 for t in durations): raise RuntimeError('Non-increasing frame simulation times')
    annotated=folder/'annotated'
    annotated.mkdir(exist_ok=True)
    manifest=[]
    start=frames[0]['sim_time_s']
    for index,frame in enumerate(frames):
        source=folder/frame['file']
        image=cv2.imread(str(source))
        if image is None: raise RuntimeError('Unreadable observer frame: '+str(source))
        cv2.rectangle(image,(0,0),(image.shape[1],60),(20,25,30),-1)
        cv2.putText(image,label+' | FIXED OBSERVER',(18,25),cv2.FONT_HERSHEY_SIMPLEX,.62,(245,245,245),1,cv2.LINE_AA)
        cv2.putText(image,f'Simulation time: {frame["sim_time_s"]-start:.1f}s  |  Cyan guides: route nodes',(18,49),cv2.FONT_HERSHEY_SIMPLEX,.5,(80,230,250),1,cv2.LINE_AA)
        target=annotated/frame['file']
        if not cv2.imwrite(str(target),image): raise RuntimeError('Could not write annotated frame')
        safe=str(target).replace('\\','/').replace("'","'\\''")
        manifest.append("file '"+safe+"'")
        manifest.append('duration '+str(durations[index] if index<len(durations) else float(np.median(durations))))
    manifest.append(manifest[-2])
    concat=folder/'frames.ffconcat'
    concat.write_text('\n'.join(manifest)+'\n',encoding='utf-8')
    executable=shutil.which('ffmpeg')
    if not executable: raise RuntimeError('FFmpeg executable not found')
    destination.parent.mkdir(parents=True,exist_ok=True)
    candidate=destination.with_name(destination.stem+'.partial.mp4')
    command=[executable,'-hide_banner','-loglevel','warning','-y','-f','concat','-safe','0','-i',str(concat),'-fps_mode','vfr','-c:v','libx264','-preset','medium','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(candidate)]
    subprocess.run(command,check=True)
    with candidate.open('r+b') as stream:
        os.fsync(stream.fileno())
    os.replace(candidate,destination)
    report={'source_frames':len(frames),'camera_position_max_delta_cm':position_delta,'camera_rotation_max_delta_deg':rotation_delta,'simulation_duration_s':frames[-1]['sim_time_s']-start,'frame_spacing_p50_s':float(np.median(durations)),'frame_spacing_max_s':max(durations),'output':str(destination),'bytes':destination.stat().st_size,'source':'Actual UE SceneCapture2D frames; fixed transform; simulation-time spacing; title overlay only'}
    write_json(destination.with_suffix('.camera_check.json'),report)
    print(json.dumps(report,indent=2))
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('folder',type=Path)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--label',default='Drone route capture')
    args=parser.parse_args()
    encode(args.folder,args.destination,args.label)

#!/usr/bin/env python3
# Runs ON device (parked). Post-drive report: summarizes how the longitudinal features behaved on
# a route. Read-only (qlogs for speed + grep of cloudlog for feature activity). Usage: drive_report.py <route>
import os, glob, sys
from cereal import log as L   # use cereal's schema (avoids duplicate-load with Params)
import zstandard
def dec(p): return zstandard.ZstdDecompressor().stream_reader(open(p,'rb')).read()
from collections import defaultdict

route=sys.argv[1]
segdirs=sorted(glob.glob('/data/media/0/realdata/%s--*'%route),
               key=lambda p:int(p.rsplit('--',1)[1]) if p.rsplit('--',1)[1].isdigit() else -1)
segdirs=[d for d in segdirs if d.rsplit('--',1)[1].isdigit()]
nseg=len(segdirs)
brakes=defaultdict(lambda:[0,0])  # cause -> [firm, hard]
dist=0.0; vmax=0; sccmap_brake=0; sla_brake=0; sla_max=0.0; nframes=0; lead_loss=0
prev_lead=False; prev_v=None; in_brake=False; bmin=0; bsrc='cruise'
plansrc='cruise'; sccmap=''; slastate=''
for sd in segdirs:
    qp=os.path.join(sd,'qlog.zst')
    if not os.path.exists(qp): continue
    try: raw=dec(qp)
    except: continue
    vego=aego=0
    try:
        for ev in L.Event.read_multiple_bytes(raw,traversal_limit_in_words=2**62):
            w=ev.which()
            if w=='carState':
                cs=ev.carState; vego=cs.vEgo; aego=cs.aEgo; nframes+=1
                vmax=max(vmax,vego); dist+=vego*0.01  # qlog carState ~ downsampled; rough
                if vego>8:
                    if aego<=-1.2:
                        if not in_brake:
                            in_brake=True; bmin=aego
                            bsrc = 'speedLimit' if 'speedLimit' in plansrc else ('sccMap' if sccmap=='turning' else (plansrc if plansrc in('lead0','lead1') else 'cruise/e2e'))
                        bmin=min(bmin,aego)
                    elif in_brake:
                        sev=1 if bmin<=-2 else 0
                        brakes[bsrc][sev]+=1
                        if bsrc=='sccMap': sccmap_brake+=1
                        if bsrc=='speedLimit': sla_brake+=1; sla_max=min(sla_max,bmin)
                        in_brake=False
            elif w=='radarState':
                st=ev.radarState.leadOne.status
                if prev_lead and not st: lead_loss+=1
                prev_lead=st
            elif w=='longitudinalPlan':
                try: plansrc=str(ev.longitudinalPlan.longitudinalPlanSource)
                except: pass
            elif w=='longitudinalPlanSP':
                try: sccmap=str(ev.longitudinalPlanSP.smartCruiseControl.map.state)
                except: pass
    except Exception: pass

# closing-assist activity from cloudlog
ca_lines=0; ca_max=0.0
for lg in glob.glob('/data/log/*') + glob.glob('/tmp/*.log'):
    try:
        with open(lg,'rb') as fh:
            for ln in fh:
                if b'closing_assist' in ln:
                    ca_lines+=1
                    try: ca_max=max(ca_max, float(ln.split(b'extra_decel=')[1].split()[0]))
                    except: pass
    except Exception: pass

# learned factors
from openpilot.common.params import Params
p=Params()
gf=p.get("HondaGasFactorParams"); wf=p.get("HondaWindFactorParams")

print("="*56)
print(f"DRIVE REPORT — route {route}")
print("="*56)
print(f"Duration:   ~{nseg} min ({nseg} segments)   Top speed: {vmax*2.237:.0f} mph")
print(f"\nBRAKING (firm/hard episodes while moving >18mph, by cause):")
tot=0
for src in sorted(brakes, key=lambda s:-sum(brakes[s])):
    firm,hard=brakes[src]; tot+=firm+hard
    tag=' <-- should be rare now' if src in('sccMap','speedLimit') else ''
    print(f"   {src:12}: {firm+hard:3d}  ({hard} hard <=-2){tag}")
print(f"   TOTAL: {tot}")
print(f"\nFEATURES:")
print(f"   Closing-assist: {ca_lines} activations logged"+(f", peak {ca_max:.2f} m/s^2" if ca_max else " (or logs rotated)"))
print(f"   Map-curve braking episodes: {sccmap_brake}  (with camera-gate, these should be REAL curves only)")
print(f"   Speed-limit braking episodes: {sla_brake}"+(f", hardest {sla_max:.2f} m/s^2 (want gentle)" if sla_brake else " (coast working)"))
print(f"   Lead cut-outs (lead lost): {lead_loss}")
print(f"\nLEARNED FACTORS: gas={gf} (band 0.6-1.6), wind={wf} (band 0.5-2.0)")
print("="*56)

# Audio-match live clips to new extraction: 8 kHz mono decode -> 20 ms RMS envelope -> normalized xcorr.
import subprocess, sys, os, json, numpy as np, glob
live_dir, new_dir, out = sys.argv[1], sys.argv[2], sys.argv[3]
def env(p):
    raw = subprocess.run(["ffmpeg","-v","error","-i",p,"-ac","1","-ar","8000","-f","s16le","-"],capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32)
    n = len(a)//160
    e = np.sqrt((a[:n*160].reshape(n,160)**2).mean(1)+1e-6)
    e = np.log(e); return (e-e.mean())/(e.std()+1e-6)
def score(a,b):
    if abs(len(a)-len(b))>max(25,0.1*max(len(a),len(b))): return -1
    n=min(len(a),len(b)); best=-1
    for s in range(-10,11):
        x=a[max(0,s):n+min(0,s)]; y=b[max(0,-s):n-max(0,s)]
        m=min(len(x),len(y))
        if m>20: best=max(best,float(np.dot(x[:m],y[:m])/m))
    return best
newf=[p for p in glob.glob(os.path.join(new_dir,"Julie","**","*.mp3"),recursive=True)]
NE={p:env(p) for p in newf}
res={}
for p in sorted(glob.glob(os.path.join(live_dir,"**","*.mp3"),recursive=True)):
    e=env(p); sc=sorted(((score(e,v),q) for q,v in NE.items()),reverse=True)[:2]
    res[os.path.relpath(p,live_dir).replace("\\","/")]=[(round(s,3),os.path.relpath(q,new_dir).replace("\\","/")) for s,q in sc]
json.dump(res,open(out,"w",encoding="utf-8"),indent=1,ensure_ascii=False)

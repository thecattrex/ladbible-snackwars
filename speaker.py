"""Cheap speaker check: median pitch over the first seconds of a clip.
John Cena ~ low male voice, Jessica Biel ~ higher female voice."""
import subprocess, numpy as np, imageio_ffmpeg
FF = imageio_ffmpeg.get_ffmpeg_exe()

def f0(src, t0, dur=3.0):
    raw = subprocess.run([FF,"-v","error","-ss",f"{t0:.2f}","-t",f"{dur:.2f}","-i",str(src),
                          "-vn","-ac","1","-ar","16000","-f","s16le","-"],capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32)/32768.0
    if len(a) < 8000: return 0.0, 0.0
    fr, hop = 1024, 512
    vals = []
    for i in range(0, len(a)-fr, hop):
        w = a[i:i+fr]
        if np.sqrt((w**2).mean()) < 0.02:      # silence
            continue
        w = w - w.mean()
        ac = np.correlate(w, w, 'full')[fr-1:]
        lo, hi = int(16000/300), int(16000/70)
        seg = ac[lo:hi]
        if seg.size == 0: continue
        p = int(np.argmax(seg)) + lo
        if ac[p] > 0.3*ac[0]:
            vals.append(16000.0/p)
    if not vals: return 0.0, 0.0
    return float(np.median(vals)), float(np.sqrt((a**2).mean()))

if __name__ == "__main__":
    import sys
    print(f0(sys.argv[1], float(sys.argv[2])))

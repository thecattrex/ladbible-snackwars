#!/bin/bash
# Rebuild after an environment reset: packages, proxy pool, per-clip media, renders.
# /var/tmp does not survive a reset; the repo and state/ do.
set -x
cd /home/user/clipper || exit 1

pip install -q imageio-ffmpeg "opencv-python-headless<5" pillow numpy yt-dlp 2>&1 | tail -2
mkdir -p /var/tmp/hf && cd /var/tmp/hf || exit 1

# 1. proxy pool
python3 - <<'PY'
import urllib.request, re
srcs = [
 "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=ipport&format=text",
 "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
 "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
 "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
]
out = set()
for u in srcs:
    try:
        t = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}),
                                   timeout=25).read().decode("utf8", "ignore")
        for line in t.splitlines():
            m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})", line)
            if m:
                out.add(f"{m.group(1)}:{m.group(2)}")
    except Exception as e:
        print("src fail", e)
open("pool.txt", "w").write("\n".join(sorted(out)) + "\n")
print("pool", len(out))
PY

cat > alive.sh <<'EOF'
#!/bin/bash
code=$(curl -s -o /dev/null -m 7 -w "%{http_code}" -x "http://$1" "https://www.youtube.com/generate_204" 2>/dev/null)
[ "$code" = "204" ] || [ "$code" = "200" ] && echo "$1"
EOF
cat > yt.sh <<'EOF'
#!/bin/bash
if timeout 50 yt-dlp --proxy "http://$1" --simulate --no-warnings -f 401 --print "%(format_id)s" \
     "https://www.youtube.com/watch?v=jszn8rFtxm4" 2>/dev/null | grep -qx 401; then echo "$1"; fi
EOF
chmod +x alive.sh yt.sh
head -2600 pool.txt | xargs -P 120 -I{} ./alive.sh {} > alive.txt 2>/dev/null
head -200 alive.txt | xargs -P 40 -I{} ./yt.sh {} > ok.txt 2>/dev/null
echo "alive $(wc -l < alive.txt) yt-ok $(wc -l < ok.txt)"

cd /home/user/clipper || exit 1
# 2. media, then 3. renders
python3 tools/fetch_clips.py 2>&1 | tail -30
bash run_all.sh
python3 tools/finalize.py 2>&1 | tail -25
echo "REBUILD DONE $(date +%H:%M)"

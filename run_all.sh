#!/bin/bash
cd /home/user/clipper
# render whatever has media, then keep sweeping until every clip is settled
for pass in $(seq 1 40); do
  python3 run_batch.py higgsfield-20vc >> batch_out.log 2>&1
  n=$(python3 -c "
import json,os
p='state/higgsfield-20vc/batch_log.json'
log=json.load(open(p)) if os.path.exists(p) else {}
print(sum(1 for v in log.values() if v.get('qa') in ('PASS','ERROR')))")
  echo "sweep $pass: $n/20 settled" >> batch_out.log
  [ "$n" -ge 20 ] && break
  sleep 45
done
echo "ALL DONE $(date +%H:%M)" >> batch_out.log

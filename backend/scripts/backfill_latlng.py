"""Fetch the GPS track (latlng stream) for a user's Strava runs that lack it.

Rows stored before latlng was requested cannot be matched by the improvement
index. Paced at one request every 10 s to stay under Strava's 100 / 15 min.

    python scripts/backfill_latlng.py --user 3
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models import Activity
from services import segment_match_service as sm
from services.agent.tool_handlers.activities import _ensure_streams

p = argparse.ArgumentParser()
p.add_argument('--user', type=int, required=True)
p.add_argument('--sleep', type=float, default=10.0)
args = p.parse_args()

app = create_app()
with app.app_context():
    ids = [a.id for a in Activity.query.filter_by(user_id=args.user, source='strava')
           .order_by(Activity.start_date.desc()) if not sm.has_latlng(a.streams)]
    print(f'{len(ids)} runs without GPS track', flush=True)
    for i, aid in enumerate(ids, 1):
        a = Activity.query.get(aid)
        ok = sm.has_latlng(_ensure_streams(a, args.user, need_latlng=True))
        print(f'{i}/{len(ids)} activity {aid}: {"ok" if ok else "no track"}', flush=True)
        time.sleep(args.sleep)

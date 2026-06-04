#!/usr/bin/env bash
set -e

LAYOUT_FILE="${LAYOUT_FILE:-/app/data/store_layout.json}"
CLIPS_DIR="${CLIPS_DIR:-/app/data/clips}"
API_BASE="${API_BASE_URL:-http://localhost:8000}"
MODEL="${YOLO_MODEL:-yolov8n.pt}"

echo "[run.sh] Waiting for API to be ready..."
until curl -sf "$API_BASE/health" > /dev/null; do
  sleep 2
done
echo "[run.sh] API is up."

for store_dir in "$CLIPS_DIR"/*/; do

  store_id=$(basename "$store_dir")

  echo "[run.sh] Processing store: $store_id"

  python3 - << EOF

import os
import sys

sys.path.insert(0, "/app")

from pipeline.detect import StoreStreamEngine

engine = StoreStreamEngine(
    store_id="$store_id",
    layout_filepath="$LAYOUT_FILE",
    model_path="$MODEL",
)

store_dir = "$store_dir"

for camera_name in sorted(os.listdir(store_dir)):

    camera_path = os.path.join(store_dir, camera_name)

    if not os.path.isdir(camera_path):
        continue

    for clip_name in sorted(os.listdir(camera_path)):

        if not clip_name.lower().endswith(
            (".mp4", ".avi", ".mov")
        ):
            continue

        clip_path = os.path.join(camera_path, clip_name)

        print(
            f"[run.sh] Camera: {camera_name} Clip: {clip_path}"
        )

        engine.process_video_feed(
            camera_name,
            clip_path
        )

        print(
            f"[run.sh] Done: {camera_name} / {clip_path}"
        )

EOF

done

echo "[run.sh] All clips processed."
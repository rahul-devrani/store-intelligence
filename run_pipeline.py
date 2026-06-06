import os
from pipeline.detect import StoreStreamEngine

# Automatically detect all stores inside data/clips
BASE_DATA_DIR = os.path.join("data", "clips")

for store_id in sorted(os.listdir(BASE_DATA_DIR)):

    store_path = os.path.join(BASE_DATA_DIR, store_id)

    if not os.path.isdir(store_path):
        continue

    print("\n" + "=" * 70)
    print(f"PROCESSING STORE: {store_id}")
    print("=" * 70)

    engine = StoreStreamEngine(
        store_id=store_id,
        layout_filepath="data/store_layout.json",
        model_path="yolov8n.pt"
    )

    total_videos = 0

    for cam in sorted(os.listdir(store_path)):

        cam_path = os.path.join(store_path, cam)

        if not os.path.isdir(cam_path):
            continue

        print(f"\nCamera: {cam}")

        for clip in sorted(os.listdir(cam_path)):

            if clip.lower().endswith(".mp4"):

                video_path = os.path.join(cam_path, clip)

                print(f"  Processing -> {clip}")

                try:
                    engine.process_video_feed(
                        camera_id=cam,
                        video_path=video_path
                    )

                    total_videos += 1

                except Exception as e:
                    print(
                        f"ERROR processing "
                        f"{store_id}/{cam}/{clip}"
                    )
                    print(str(e))

    print(
        f"\nProcessed {total_videos} videos "
        f"for {store_id}"
    )

    engine.finalize_store_session()

    print(f"Store session finalized: {store_id}")

print("\n" + "=" * 70)
print("ALL STORES PROCESSED SUCCESSFULLY")
print("=" * 70)
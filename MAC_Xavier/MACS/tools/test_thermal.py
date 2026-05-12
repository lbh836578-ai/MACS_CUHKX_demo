import cv2
import time

def run_test(label, width, height, warmup):
    print(f"\n=== {label} ===")
    cap = cv2.VideoCapture('/dev/video0', cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M','J','P','G'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, 25)

    if not cap.isOpened():
        print("FAILED to open")
        cap.release()
        return

    print("Opened OK")

    if warmup:
        # 丢掉前5帧 + sleep（海康相机预热）
        for i in range(5):
            cap.read()
            time.sleep(0.1)

    ret, frame = cap.read()
    if ret:
        out = f"thermal_{label}.jpg"
        print(f"Got frame: {frame.shape}, min={frame.min()}, max={frame.max()}")
        cv2.imwrite(out, frame)
        print(f"Saved {out}")
    else:
        print("Read failed")

    cap.release()

# A: 保留预热 sleep，分辨率降为 120x160
run_test("A_120x160_warmup", width=120, height=160, warmup=True)

# B: 保留 240x320，去掉预热和 sleep
run_test("B_240x320_nowarmup", width=240, height=320, warmup=False)
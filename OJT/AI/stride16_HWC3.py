import numpy as np
import cv2

def align_up(v, a=16):
    return (v + (a-1)) & ~(a-1)

H, W = 321, 481
sigma = 15

# 원본 이미지 로드
img = cv2.imread("./BUIFD-master/Training/input.png")  # BGR
img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0  # 0..1

# Gaussian noise
noise = np.random.normal(0.0, sigma / 255.0, img.shape).astype(np.float32)
noisy = np.clip(img + noise, 0.0, 1.0)

# -------------------------
# 1) PNG 저장 (확인용)
# -------------------------
noisy_png = np.clip(noisy * 255.0, 0, 255).astype(np.uint8)
cv2.imwrite(
    f"input_noisy_sigma{sigma}.png",
    cv2.cvtColor(noisy_png, cv2.COLOR_RGB2BGR)
)

# -------------------------
# 2) int8 raw (stride16)
# -------------------------
# quant to int8 with scale 128 (0..127)
q = np.clip(np.round(noisy * 128.0), 0, 127).astype(np.int8)  # HWC3

row_bytes = W * 3
stride = align_up(row_bytes, 16)

buf = np.zeros((H, stride), dtype=np.int8)
buf[:, :row_bytes] = q.reshape(H, row_bytes)

buf.tofile(f"input_noisy_sigma{sigma}_s128_stride16.i8.raw")

print("Saved:")
print(f" - input_noisy_sigma{sigma}.png")
print(f" - input_noisy_sigma{sigma}_s128_stride16.i8.raw")

import cv2
import numpy as np
import sys

def make_even_size(bgr: np.ndarray, mode: str = "crop"):
    h, w = bgr.shape[:2]
    if (w % 2 == 0) and (h % 2 == 0):
        return bgr, (w, h), (w, h)

    if mode == "crop":
        w2 = w - (w % 2)
        h2 = h - (h % 2)
        return bgr[:h2, :w2].copy(), (w, h), (w2, h2)

    if mode == "pad":
        pad_w = w % 2
        pad_h = h % 2
        bgr2 = cv2.copyMakeBorder(bgr, 0, pad_h, 0, pad_w, borderType=cv2.BORDER_REPLICATE)
        h2, w2 = bgr2.shape[:2]
        return bgr2, (w, h), (w2, h2)

    raise ValueError("mode must be 'crop' or 'pad'")

def png_to_nv12(in_path: str, out_path: str, even_mode: str = "crop"):
    bgr = cv2.imread(in_path, cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"Failed to load image: {in_path}")

    bgr, (w0, h0), (w, h) = make_even_size(bgr, even_mode)

    # OpenCV: BGR -> I420 (YUV420 planar)
    yuv_i420 = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420)

    # 가장 안전한 방식: 1D로 펼쳐서 byte 단위로 쪼개기
    flat = yuv_i420.reshape(-1)

    y_size  = w * h
    uv_size = (w // 2) * (h // 2)

    if flat.size < y_size + 2 * uv_size:
        raise RuntimeError(
            f"I420 buffer too small: got {flat.size}, expected {y_size + 2*uv_size}"
        )

    Y = flat[0:y_size].reshape(h, w)
    U = flat[y_size:y_size + uv_size].reshape(h // 2, w // 2)
    V = flat[y_size + uv_size:y_size + 2 * uv_size].reshape(h // 2, w // 2)

    # NV12: UV interleaved
    UV = np.empty((h // 2, w), dtype=np.uint8)
    UV[:, 0::2] = U
    UV[:, 1::2] = V

    nv12 = np.concatenate([Y.reshape(-1), UV.reshape(-1)])
    nv12.tofile(out_path)

    print(f"[OK] {in_path} -> {out_path}")
    print(f"     Original: {w0}x{h0}")
    print(f"     NV12:     {w}x{h} (even_mode={even_mode})")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python png_nv12.py input.png output.img [crop|pad]")
        sys.exit(1)

    in_path = sys.argv[1]
    out_path = sys.argv[2]
    mode = sys.argv[3].lower() if len(sys.argv) >= 4 else "crop"

    png_to_nv12(in_path, out_path, even_mode=mode)

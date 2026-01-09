import os
import numpy as np
import cv2
import matplotlib.pyplot as plt

# ============================================================
# NV12 1-frame loader/saver
# ============================================================
def read_nv12_oneframe(path: str, w: int, h: int):
    frame_size = w * h * 3 // 2
    data = np.fromfile(path, dtype=np.uint8)
    if data.size != frame_size:
        raise ValueError(f"Expected {frame_size} bytes, got {data.size} ({path})")
    y = data[:w*h].reshape((h, w))
    uv = data[w*h:].reshape((h//2, w))  # NV12 interleaved UV
    return y, uv

def write_nv12_oneframe(path: str, y: np.ndarray, uv: np.ndarray):
    h, w = y.shape
    if uv.shape != (h//2, w):
        raise ValueError(f"uv shape must be {(h//2, w)}, got {uv.shape}")
    y8 = np.clip(y, 0, 255).astype(np.uint8)
    uv8 = np.clip(uv, 0, 255).astype(np.uint8)

    out = np.empty(w*h*3//2, dtype=np.uint8)
    out[:w*h] = y8.reshape(-1)
    out[w*h:] = uv8.reshape(-1)
    out.tofile(path)

# ============================================================
# Basic utils
# ============================================================
def normalize01(x: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    x = x.astype(np.float32)
    mn = float(x.min())
    mx = float(x.max())
    if mx - mn < eps:
        return np.zeros_like(x, dtype=np.float32)
    return ((x - mn) / (mx - mn)).astype(np.float32)

def sobel_grad_mag(Y: np.ndarray) -> np.ndarray:
    Y = Y.astype(np.float32)
    gx = cv2.Sobel(Y, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(Y, cv2.CV_32F, 0, 1, ksize=3)
    return np.sqrt(gx*gx + gy*gy).astype(np.float32)

# ============================================================
# Robust structure map C (edge/structure reliability)
# ============================================================
def build_C_robust(Y: np.ndarray, p_hi=99.0, floor=0.07, gamma=1.4) -> np.ndarray:
    G = sobel_grad_mag(Y).astype(np.float32)
    s = np.percentile(G, p_hi) + 1e-6
    C = np.clip(G / s, 0.0, 1.0)
    C = np.clip((C - floor) / (1.0 - floor + 1e-6), 0.0, 1.0)
    C = C ** gamma
    return C.astype(np.float32)

def build_maps(Y: np.ndarray, sigma_E: float = 0.20, y_thr: float = 0.35):
    # well-exposedness (mid-tone reliability)
    E = np.exp(-((Y - 0.5) ** 2) / (2 * sigma_E * sigma_E)).astype(np.float32)
    # contrast/structure reliability
    C = build_C_robust(Y).astype(np.float32)
    # shadow mask (often used as noise-risk / shadow mask)
    N = np.clip((y_thr - Y) / max(y_thr, 1e-6), 0.0, 1.0).astype(np.float32)
    return E, C, N

# ============================================================
# Bilateral multi-scale decomposition -> 4 bands
# ============================================================
def bilateral_smooth(Y: np.ndarray, sigma_s: float, sigma_r: float, d: int = -1) -> np.ndarray:
    """
    Y: float32 [0,1]
    sigma_s: spatial sigma (pixels)
    sigma_r: range sigma (0..1 domain)
    """
    Y = Y.astype(np.float32, copy=False)
    out = cv2.bilateralFilter(
        Y, d=d, sigmaColor=float(sigma_r), sigmaSpace=float(sigma_s),
        borderType=cv2.BORDER_REFLECT
    )
    return out.astype(np.float32)

def multiband_bilateral_decomposition(
    Y: np.ndarray,
    s1=4,  r1=0.06,   # fine
    s2=12, r2=0.10,   # medium
    s3=32, r3=0.18    # coarse
):
    base1 = bilateral_smooth(Y, sigma_s=s1, sigma_r=r1)
    base2 = bilateral_smooth(Y, sigma_s=s2, sigma_r=r2)
    base3 = bilateral_smooth(Y, sigma_s=s3, sigma_r=r3)

    B1 = base3
    B2 = base2 - base3
    B3 = base1 - base2
    B4 = Y - base1
    return base1, base2, base3, (B1, B2, B3, B4)

# ============================================================
# Visualization helpers (OpenCV)
# ============================================================
def to_uint8_01(x: np.ndarray) -> np.ndarray:
    x = np.clip(x.astype(np.float32), 0.0, 1.0)
    return (x * 255.0 + 0.5).astype(np.uint8)

def label_gray(gray8: np.ndarray, text: str) -> np.ndarray:
    bgr = cv2.cvtColor(gray8, cv2.COLOR_GRAY2BGR)
    cv2.putText(bgr, text, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2, cv2.LINE_AA)
    return bgr

def vis_signed_auto(x: np.ndarray, p=99.5) -> np.ndarray:
    x = x.astype(np.float32)
    s = np.percentile(np.abs(x), p) + 1e-8
    v = np.clip(x / (2*s) + 0.5, 0.0, 1.0)
    return (v * 255.0 + 0.5).astype(np.uint8)

def show_bases_grid(Y, base1, base2, base3, title="Bases (Y/base1/base2/base3)"):
    yv  = label_gray(to_uint8_01(Y),     "Y")
    b1v = label_gray(to_uint8_01(base1), "base1")
    b2v = label_gray(to_uint8_01(base2), "base2")
    b3v = label_gray(to_uint8_01(base3), "base3")
    top = np.hstack([yv, b1v])
    bot = np.hstack([b2v, b3v])
    grid = np.vstack([top, bot])
    cv2.imshow(title, grid)

def show_bands_grid(B1, B2, B3, B4, title="Bands (B1~B4)"):
    v1 = label_gray(to_uint8_01(B1), "B1 (base3)")
    v2 = label_gray(vis_signed_auto(B2), "B2 (base2-base3)")
    v3 = label_gray(vis_signed_auto(B3), "B3 (base1-base2)")
    v4 = label_gray(vis_signed_auto(B4), "B4 (Y-base1)")
    top = np.hstack([v1, v2])
    bot = np.hstack([v3, v4])
    grid = np.vstack([top, bot])
    cv2.imshow(title, grid)

def show_maps_grid(E, C, N, title="Maps (E/C/N/zero)"):
    e = label_gray(to_uint8_01(E), "E")
    c = label_gray(to_uint8_01(C), "C")
    n = label_gray(to_uint8_01(N), "N")
    z = label_gray(np.zeros_like(to_uint8_01(E)), "-")
    top = np.hstack([e, c])
    bot = np.hstack([n, z])
    grid = np.vstack([top, bot])
    cv2.imshow(title, grid)

def show_gain_grid_centered(G1, G2, G3, G4, span=0.5, title="Gains (centered @1.0)"):
    def vis_center(g):
        g = g.astype(np.float32)
        v = (g - 1.0) / float(span)
        v = np.clip(v, -1.0, 1.0)
        v = (v * 0.5 + 0.5)
        return (v * 255.0 + 0.5).astype(np.uint8)

    g1 = label_gray(vis_center(G1), "G1")
    g2 = label_gray(vis_center(G2), "G2")
    g3 = label_gray(vis_center(G3), "G3")
    g4 = label_gray(vis_center(G4), "G4")
    top = np.hstack([g1, g2])
    bot = np.hstack([g3, g4])
    grid = np.vstack([top, bot])
    cv2.imshow(title, grid)

def show_db_grid(dB1, dB2, dB3, dB4, title="dB = (G-1)*B (auto)"):
    v1 = label_gray(vis_signed_auto(dB1), "dB1")
    v2 = label_gray(vis_signed_auto(dB2), "dB2")
    v3 = label_gray(vis_signed_auto(dB3), "dB3")
    v4 = label_gray(vis_signed_auto(dB4), "dB4")
    top = np.hstack([v1, v2])
    bot = np.hstack([v3, v4])
    grid = np.vstack([top, bot])
    cv2.imshow(title, grid)

# ============================================================
# Edge-preserving check (line profile)
# ============================================================
def plot_line_profile(Y_in, Y_out, x=None, y=None, half_len=80, horizontal=True):
    H, W = Y_in.shape
    if x is None: x = W//2
    if y is None: y = H//2
    x = int(np.clip(x, 0, W-1))
    y = int(np.clip(y, 0, H-1))

    if horizontal:
        x0 = max(0, x-half_len); x1 = min(W, x+half_len)
        p_in  = Y_in[y, x0:x1]
        p_out = Y_out[y, x0:x1]
        axis = np.arange(x0, x1)
        xlabel = "x (pixel)"
    else:
        y0 = max(0, y-half_len); y1 = min(H, y+half_len)
        p_in  = Y_in[y0:y1, x]
        p_out = Y_out[y0:y1, x]
        axis = np.arange(y0, y1)
        xlabel = "y (pixel)"

    plt.figure(figsize=(12,4))
    plt.plot(axis, p_in,  label="Y_in")
    plt.plot(axis, p_out, label="Y_out")
    plt.title(f"Line profile @ ({x},{y})")
    plt.xlabel(xlabel); plt.ylabel("Y")
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend()
    plt.tight_layout()
    plt.show()

# ============================================================
# Main ISP core: bilateral multi-band + adaptive gain + fusion
# ============================================================
def multiband_pseudo_dr_y_bilateral(
    Y: np.ndarray,
    # bilateral scales (for 328x220): try (4,12,32). For 1080p: (8,24,64)
    s1=4,  r1=0.06,
    s2=12, r2=0.10,
    s3=32, r3=0.18,
    # maps
    sigma_E=0.20,
    y_thr=0.35,
    # gains
    k1=0.30,   # shadow lift strength (B1)
    k2L=0.80,  # shadow local lift (B2)
    k2H=0.15,  # halo damper from C (B2 gate)
    k3=0.25,   # edge contrast (B3)
    k4=0.15,   # texture (B4)
    # safety
    clamp_g2_min=0.70,
    clamp_all=True
):
    Y = Y.astype(np.float32)

    # --- decomposition (bilateral)
    base1, base2, base3, (B1, B2, B3, B4) = multiband_bilateral_decomposition(
        Y, s1=s1, r1=r1, s2=s2, r2=r2, s3=s3, r3=r3
    )

    # --- maps
    E, C, N = build_maps(Y, sigma_E=sigma_E, y_thr=y_thr)
    C1 = np.clip(C, 0.0, 1.0)

    # --- gains (adaptive)
    # B1: shadow lift (kept from your design)
    G1 = np.exp(k1 * (0.5 - E)).astype(np.float32)

    # B2: local lift + halo damper
    G2L = 1.0 + k2L * N * (0.3 + 0.7*(1.0 - E))
    G2H = 1.0 - k2H * C1
    G2H = np.clip(G2H, clamp_g2_min, 1.0)  # avoid too strong gating / negatives
    G2  = (G2L * G2H).astype(np.float32)

    # B3/B4: perceptual detail
    G3 = (1.0 + k3 * C1 * (0.5 + 0.5*E)).astype(np.float32)
    G4 = (1.0 + k4 * C1 * (0.5 + 0.5*E) * (1.0 - 0.5*N)).astype(np.float32)

    # optional global clamps (tune as you like)
    if clamp_all:
        G1 = np.clip(G1, 0.8, 1.8)
        G2 = np.clip(G2, 0.7, 1.4)
        G3 = np.clip(G3, 0.7, 1.4)
        G4 = np.clip(G4, 0.6, 1.3)

    # --- delta bands (for debug)
    dB1 = (G1 - 1.0) * B1
    dB2 = (G2 - 1.0) * B2
    dB3 = (G3 - 1.0) * B3
    dB4 = (G4 - 1.0) * B4

    # --- debug stats
    def stat(name, x):
        ax = np.abs(x)
        print(f"{name}: mean(abs)={ax.mean():.6g}, max(abs)={ax.max():.6g}, min={x.min():.6g}, max={x.max():.6g}")

    print("\n=== Band / Gain / dB stats ===")
    stat("B2", B2); stat("B3", B3); stat("B4", B4)
    stat("G2-1", G2-1); stat("G3-1", G3-1); stat("G4-1", G4-1)
    stat("dB2", dB2); stat("dB3", dB3); stat("dB4", dB4)

    # --- fusion
    Y_out = (G1 * B1 + G2 * B2 + G3 * B3 + G4 * B4).astype(np.float32)

    # keep in [0,1]
    Y_out = np.clip(Y_out, 0.0, 1.0).astype(np.float32)

    # --- debug windows
    show_bases_grid(Y, base1, base2, base3)
    show_bands_grid(B1, B2, B3, B4)
    show_maps_grid(E, C1, N)
    show_gain_grid_centered(G1, G2, G3, G4, span=0.5)
    show_db_grid((G1-1)*B1, dB2, dB3, dB4)

    return Y_out, (E, C1, N)

def find_failure_points_by_dY(Y_in, Y_out, C, c_thr=0.2, topk=10):
    """
    edge 영역(C>c_thr)에서 |dY|=|Y_out-Y_in|가 큰 지점 topk 찾기
    return: [(x,y,val), ...] val = |dY|
    """
    dY = (Y_out - Y_in).astype(np.float32)
    edge = (C > c_thr)

    score = np.abs(dY) * edge.astype(np.float32)

    # top-k 좌표
    flat = score.reshape(-1)
    idxs = np.argpartition(flat, -topk)[-topk:]
    idxs = idxs[np.argsort(flat[idxs])[::-1]]

    pts = []
    H, W = Y_in.shape
    for idx in idxs:
        y = idx // W
        x = idx % W
        pts.append((int(x), int(y), float(score[y, x])))
    return pts

def draw_points_on_bgr(bgr, pts, color=(0,0,255), r=4):
    out = bgr.copy()
    for (x,y,v) in pts:
        cv2.circle(out, (x,y), r, color, 2, cv2.LINE_AA)
        cv2.putText(out, f"{v:.3f}", (x+6, y-6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    return out

def grad_mag(Y):
    gx = cv2.Sobel(Y.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(Y.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    return np.sqrt(gx*gx + gy*gy)

def find_failure_points_by_grad_ratio(Y_in, Y_out, C, c_thr=0.2, topk=10):
    g_in  = grad_mag(Y_in)
    g_out = grad_mag(Y_out)

    ratio = (g_out + 1e-6) / (g_in + 1e-6)

    edge = (C > c_thr)

    # 이상치 점수: 1에서 멀수록 큰 점수
    score = np.abs(ratio - 1.0) * edge.astype(np.float32)

    flat = score.reshape(-1)
    idxs = np.argpartition(flat, -topk)[-topk:]
    idxs = idxs[np.argsort(flat[idxs])[::-1]]

    pts = []
    H, W = Y_in.shape
    for idx in idxs:
        y = idx // W
        x = idx % W
        pts.append((int(x), int(y), float(ratio[y, x])))
    return pts, ratio

def crop_fixed(img, x, y, r=80):
    """
    항상 (2r x 2r) 크기의 crop을 반환.
    경계 밖은 padding으로 채워서 shape 불일치 방지.
    """
    H, W = img.shape[:2]
    x = int(x); y = int(y)
    r = int(r)

    x0, x1 = x - r, x + r
    y0, y1 = y - r, y + r

    # 필요한 패딩 계산
    pad_l = max(0, -x0)
    pad_t = max(0, -y0)
    pad_r = max(0, x1 - W)
    pad_b = max(0, y1 - H)

    # 유효 범위로 clip
    x0c, x1c = max(0, x0), min(W, x1)
    y0c, y1c = max(0, y0), min(H, y1)

    patch = img[y0c:y1c, x0c:x1c]

    # 패딩으로 항상 고정 크기 만들기
    if pad_l or pad_t or pad_r or pad_b:
        patch = cv2.copyMakeBorder(
            patch, pad_t, pad_b, pad_l, pad_r,
            borderType=cv2.BORDER_CONSTANT, value=0
        )

    # 최종 shape 강제 (혹시 1px 오차 방지)
    patch = patch[:2*r, :2*r]
    return patch, (max(0, x0), max(0, y0)), (pad_l, pad_t)

def grad_mag(Y):
    gx = cv2.Sobel(Y.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(Y.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    return np.sqrt(gx*gx + gy*gy)

def show_failure_zoom(bgr_in, bgr_out, Y_in, Y_out, C, x, y, r=80):
    """
    3x2 grid:
      [IN, OUT, |IN-OUT|]
      [C,  |dY|, grad_ratio]
    항상 동일 크기 패치로 만들어 vstack/hstack 에러 방지.
    """
    dY = (Y_out - Y_in).astype(np.float32)
    g_in = grad_mag(Y_in)
    g_out = grad_mag(Y_out)
    ratio = (g_out + 1e-6) / (g_in + 1e-6)

    zin,  _, (pl, pt) = crop_fixed(bgr_in,  x, y, r=r)
    zout, _, _        = crop_fixed(bgr_out, x, y, r=r)

    dYc,  _, _        = crop_fixed(dY,    x, y, r=r)
    rc,   _, _        = crop_fixed(ratio, x, y, r=r)
    Cc,   _, _        = crop_fixed(C,     x, y, r=r)

    # |IN-OUT| (BGR)
    diff = cv2.absdiff(zin, zout)

    # |dY| 시각화
    abs_dY = np.abs(dYc)
    s = np.percentile(np.abs(dY), 99.5) + 1e-8
    dY_vis = (np.clip(abs_dY / s, 0.0, 1.0) * 255).astype(np.uint8)
    dY_vis = cv2.cvtColor(dY_vis, cv2.COLOR_GRAY2BGR)

    # grad ratio 시각화 (1.0이 회색)
    span = 0.5
    rv = np.clip((rc - 1.0) / span, -1.0, 1.0)
    rv = (rv * 0.5 + 0.5)
    r_vis = (rv * 255).astype(np.uint8)
    r_vis = cv2.cvtColor(r_vis, cv2.COLOR_GRAY2BGR)

    # C 시각화
    C_vis = (np.clip(Cc, 0.0, 1.0) * 255).astype(np.uint8)
    C_vis = cv2.cvtColor(C_vis, cv2.COLOR_GRAY2BGR)

    # 크롭 내부 좌표(패딩 고려)
    cx = r - pl
    cy = r - pt
    for img in [zin, zout, diff, C_vis, dY_vis, r_vis]:
        cv2.circle(img, (cx, cy), 4, (0, 0, 255), 2, cv2.LINE_AA)

    # 라벨
    def put_label(img, text):
        out = img.copy()
        cv2.putText(out, text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2, cv2.LINE_AA)
        return out

    zin  = put_label(zin,  "IN")
    zout = put_label(zout, "OUT")
    diff = put_label(diff, "|IN-OUT|")
    C_vis = put_label(C_vis, "C (edge)")
    dY_vis = put_label(dY_vis, "|dY|")
    r_vis = put_label(r_vis, "grad ratio")

    top = np.hstack([zin, zout, diff])
    bot = np.hstack([C_vis, dY_vis, r_vis])
    grid = np.vstack([top, bot])

    cv2.imshow(f"FAIL ZOOM @ ({x},{y})", grid)

# ============================================================
# Main
# ============================================================
def main():
    # ---------- Set your NV12 size / paths ----------
    W, H = 1658, 1104
    in_name  = "./img/scenary.img"   # NV12 file
    out_name = "./img/output_bilateral.img"

    base_dir = os.path.dirname(os.path.abspath(__file__))
    in_path  = os.path.join(base_dir, in_name)
    out_path = os.path.join(base_dir, out_name)

    # ---------- Read input ----------
    y8, uv = read_nv12_oneframe(in_path, W, H)
    Y = (y8.astype(np.float32) / 255.0)

    # ---------- Process (Y only) ----------
    Y_out, (E, C, N) = multiband_pseudo_dr_y_bilateral(
        Y,
        # bilateral scales (tune)
        s1=4,  r1=0.06,
        s2=12, r2=0.10,
        s3=32, r3=0.18,
        # maps
        sigma_E=0.20,
        y_thr=0.35,
        # gains
        k1=0.30,
        k2L=0.80,
        k2H=0.15,
        k3=0.25,
        k4=0.15,
        clamp_g2_min=0.70,
        clamp_all=True
    )

    y_out8 = (Y_out * 255.0 + 0.5).astype(np.uint8)

    # ---------- Write output (NV12: keep UV) ----------
    write_nv12_oneframe(out_path, y_out8, uv)
    print(f"\nOK: wrote {out_name} (NV12)")

    # ---------- Display input/output side-by-side ----------
#    yuv_in  = np.vstack([y8, uv]).reshape((H * 3 // 2, W))
#    yuv_out = np.vstack([y_out8, uv]).reshape((H * 3 // 2, W))
#    bgr_in  = cv2.cvtColor(yuv_in,  cv2.COLOR_YUV2BGR_NV12)
#    bgr_out = cv2.cvtColor(yuv_out, cv2.COLOR_YUV2BGR_NV12)
#
#    vis = np.hstack([bgr_in, bgr_out])
#    cv2.imshow("Input (Left) | Output (Right) [NV12]", vis)

    # -----------------------------
    # toggle view
    # -----------------------------
    yuv_in  = np.vstack([y8, uv]).reshape((H * 3 // 2, W))
    yuv_out = np.vstack([y_out8, uv]).reshape((H * 3 // 2, W))

    bgr_in  = cv2.cvtColor(yuv_in,  cv2.COLOR_YUV2BGR_NV12)
    bgr_out = cv2.cvtColor(yuv_out, cv2.COLOR_YUV2BGR_NV12)

    def draw_label(img: np.ndarray, text: str) -> np.ndarray:
        """좌상단 라벨 오버레이 (원본 보호 위해 copy)"""
        out = img.copy()
        # 텍스트
        cv2.putText(out, text, (20, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3, cv2.LINE_AA)
        return out

    win = "NV12 Toggle (1: toggle, 0: quit)"
    show_output = False  # False=input, True=output

    while True:
        frame = bgr_out if show_output else bgr_in
        label = "OUTPUT" if show_output else "INPUT"
        frame_labeled = draw_label(frame, label)

        # 화면이 너무 크면 축소
        max_width = 1600
        hh, ww = frame_labeled.shape[:2]
        if ww > max_width:
            scale = max_width / ww
            disp = cv2.resize(frame_labeled, (int(ww * scale), int(hh * scale)), interpolation=cv2.INTER_AREA)
        else:
            disp = frame_labeled

        cv2.imshow(win, disp)

        key = cv2.waitKey(0) & 0xFF
        if key == ord('1'):
            show_output = not show_output
        elif key == ord('0'):
            break

    cv2.destroyAllWindows()

    # 1) 실패 후보점 자동 탐색 (dY 기반)
    pts_dy = find_failure_points_by_dY(Y, Y_out, C, c_thr=0.2, topk=5)
    print("Top dY failure pts:", pts_dy)

    # 2) 실패 후보점 자동 탐색 (gradient ratio 기반)
    pts_gr, ratio = find_failure_points_by_grad_ratio(Y, Y_out, C, c_thr=0.2, topk=5)
    print("Top grad-ratio failure pts (x,y,ratio):", pts_gr)

    # 3) 원본/출력 BGR에 표시해서 확인
    marked_in  = draw_points_on_bgr(bgr_in,  pts_dy, color=(0,255,255))
    marked_out = draw_points_on_bgr(bgr_out, pts_dy, color=(0,255,255))
    cv2.imshow("Input marked (dY hotspots)", marked_in)
    cv2.imshow("Output marked (dY hotspots)", marked_out)

    # 4) 가장 큰 1개 확대해서 실패 형태 확인
    x, y, v = pts_gr[0]
    show_failure_zoom(bgr_in, bgr_out, Y, Y_out, C, x, y, r=80)

    # ---------- Edge-preserving check (auto: strongest edge from C) ----------
    # pick strongest edge location
    yy, xx = np.unravel_index(np.argmax(C), C.shape)
    print(f"\nLine profile point (strongest C): (x={xx}, y={yy})")
    plot_line_profile(Y, Y_out, x=xx, y=yy, horizontal=True)
    plot_line_profile(Y, Y_out, x=xx, y=yy, horizontal=False)

    print("\nPress any key on an OpenCV window to exit...")
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()

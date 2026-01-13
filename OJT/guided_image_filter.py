import os
import numpy as np
import matplotlib.pyplot as plt
import cv2

# ============================================================
# YUV420  (Y + U + V) 1-frame loader/saver
# ============================================================
def read_nv12_oneframe(path: str, w: int, h: int):
    frame_size = w * h * 3 // 2
    data = np.fromfile(path, dtype=np.uint8)
    if data.size != frame_size:
        raise ValueError(f"Expected {frame_size} bytes, got {data.size}")

    y = data[:w*h].reshape((h, w))
    uv = data[w*h:].reshape((h//2, w))   # NV12: interleaved UV
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
# Guided Filter (O(N)) with integral-image box filter
# ============================================================
def _boxfilter_integral(img: np.ndarray, r: int) -> np.ndarray:
    if r <= 0:
        return img.copy()

    H, W = img.shape
    pad = r
    I = np.pad(img, ((pad, pad), (pad, pad)), mode="reflect")

    S = np.zeros((I.shape[0] + 1, I.shape[1] + 1), dtype=np.float64)
    S[1:, 1:] = np.cumsum(np.cumsum(I.astype(np.float64), axis=0), axis=1)

    y = np.arange(H) + pad
    x = np.arange(W) + pad
    y0 = y - r
    y1 = y + r + 1
    x0 = x - r
    x1 = x + r + 1

    Y0 = y0[:, None]
    Y1 = y1[:, None]
    X0 = x0[None, :]
    X1 = x1[None, :]

    sum_ = (S[Y1, X1] - S[Y0, X1] - S[Y1, X0] + S[Y0, X0])
    return sum_.astype(img.dtype)

def guided_filter_gray(I: np.ndarray, p: np.ndarray, r: int, eps: float) -> np.ndarray:
    if I.shape != p.shape:
        raise ValueError("I and p must have the same shape.")
    if eps <= 0:
        raise ValueError("eps must be > 0")

    I = I.astype(np.float32, copy=False)
    p = p.astype(np.float32, copy=False)

    ones = np.ones_like(I, dtype=np.float32)
    N = _boxfilter_integral(ones, r)

    mean_I  = _boxfilter_integral(I, r) / N       # 주변 밝기 평균
    mean_p  = _boxfilter_integral(p, r) / N       # 주변 출력 평균
    mean_Ip = _boxfilter_integral(I * p, r) / N   # 밝기x출력 평균
    mean_II = _boxfilter_integral(I * I, r) / N   # 밝기^2 평균

    cov_Ip = mean_Ip - mean_I * mean_p
    # 엣지인지 아닌지 판단
    var_I  = mean_II - mean_I * mean_I  # var_I 작으면 평평 / 크면 엣지 있음

    a = cov_Ip / (var_I + eps)     # eps는 안전장치(너무 민감해지지 마라)
    # a ≈ 0 → 입력 무시 → 평균값 -> 평평
    # a ≈ 1 → 입력 그대로 따라감 -> 엣지
    # a > 1 → 입력 변화 더 강조
    b = mean_p - a * mean_I

    mean_a = _boxfilter_integral(a, r) / N
    mean_b = _boxfilter_integral(b, r) / N
    q = mean_a * I + mean_b
    return q

    # “Y를 엣지는 살리면서 부드럽게”
def guided_smooth(Y: np.ndarray, r: int, eps: float) -> np.ndarray:
    return guided_filter_gray(Y, Y, r, eps)

# ============================================================
# Maps (Exposure Fusion spirit): E, C, N
# ============================================================
def sobel_grad_mag(Y: np.ndarray) -> np.ndarray:
    Yp = np.pad(Y, ((1, 1), (1, 1)), mode="reflect")
    gx = (
        -1 * Yp[:-2, :-2] + 1 * Yp[:-2, 2:]
        -2 * Yp[1:-1, :-2] + 2 * Yp[1:-1, 2:]
        -1 * Yp[2:, :-2] + 1 * Yp[2:, 2:]
    )
    gy = (
        -1 * Yp[:-2, :-2] -2 * Yp[:-2, 1:-1] -1 * Yp[:-2, 2:]
        +1 * Yp[2:, :-2] +2 * Yp[2:, 1:-1] +1 * Yp[2:, 2:]
    )
    return np.sqrt(gx * gx + gy * gy).astype(np.float32)

def normalize01(x: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    mn = float(x.min())
    mx = float(x.max())
    if mx - mn < eps:
        return np.zeros_like(x, dtype=np.float32)
    return ((x - mn) / (mx - mn)).astype(np.float32)

def build_C_fixed(Y, c_scale):
    G = sobel_grad_mag(Y)                 # 0~대략?
    C = np.clip(G / c_scale, 0.0, 1.0)    # 고정 스케일
    return C.astype(np.float32)

def build_C_mediatek(Y, thr_low=0.02, thr_high=0.10):
    G = sobel_grad_mag(Y)
    C = (G - thr_low) / (thr_high - thr_low)
    C = np.clip(C, 0.0, 1.0)
    return C.astype(np.float32)

def build_C_robust(Y, p_hi=99.0, floor=0.07, gamma=1.4):
    G = sobel_grad_mag(Y).astype(np.float32)
    s = np.percentile(G, p_hi) + 1e-6       # robust scale
    C = np.clip(G / s, 0.0, 1.0)

    # 텍스처/노이즈 바닥 컷
    C = np.clip((C - floor) / (1.0 - floor), 0.0, 1.0)

    # 강한 구조 엣지만 상대적으로 강조
    C = C ** gamma

    return C

def build_maps(Y: np.ndarray, sigma_E: float = 0.20, y_thr: float = 0.25):
    # well-exposedness (mid-tone reliability)
    E = np.exp(-((Y - 0.5) ** 2) / (2 * sigma_E * sigma_E)).astype(np.float32)

    # contrast/edge reliability
    #C = normalize01(sobel_grad_mag(Y)) # 개념적 구현
    #C = build_C_fixed(Y, 1.0)
    #C = build_C_mediatek(Y) # 구현
    C = build_C_robust(Y) # 구조적 엣지 검출 구현

    # shadow noise risk
    N = np.clip((y_thr - Y) / max(y_thr, 1e-6), 0.0, 1.0).astype(np.float32)
    return E, C, N

# ============================================================
# Visualization helpers (OpenCV)
# ============================================================
def band_to_vis8(band: np.ndarray, scale: float) -> np.ndarray:
    vis = band.astype(np.float32) * float(scale)
    vis = np.clip(vis + 0.5, 0.0, 1.0)            # 0 -> 0.5(회색)
    return (vis * 255.0 + 0.5).astype(np.uint8)

def put_label(gray8: np.ndarray, text: str) -> np.ndarray:
    bgr = cv2.cvtColor(gray8, cv2.COLOR_GRAY2BGR)
    cv2.putText(bgr, text, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 2, cv2.LINE_AA)
    return bgr

def to_uint8_01(x: np.ndarray) -> np.ndarray:
    x = np.clip(x.astype(np.float32), 0.0, 1.0)
    return (x * 255.0 + 0.5).astype(np.uint8)

def tile4(a,b,c,d):
    return np.vstack([np.hstack([a,b]), np.hstack([c,d])])

def show_bases_grid(Y: np.ndarray, base1: np.ndarray, base2: np.ndarray, base3: np.ndarray, title="Bases"):
    yv  = put_label(to_uint8_01(Y),     "Y")
    b1v = put_label(to_uint8_01(base1), "base1")
    b2v = put_label(to_uint8_01(base2), "base2")
    b3v = put_label(to_uint8_01(base3), "base3")

    # 2x2 타일
    grid = tile4(yv, b1v, b2v, b3v)

    # 너무 크면 축소
    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        s = max_width / w
        grid = cv2.resize(grid, (int(w*s), int(h*s)), interpolation=cv2.INTER_AREA)

    cv2.imshow(title, grid)

def show_bands_grid(B1, B2, B3, B4, title="Bands"):
    v1 = put_label(band_to_vis8(B1, scale=1.0),  "B1")
    v2 = put_label(band_to_vis8(B2, scale=4.0),  "B2")
    v3 = put_label(band_to_vis8(B3, scale=8.0),  "B3")
    v4 = put_label(band_to_vis8(B4, scale=16.0), "B4")

    # 2x2 타일
    grid = tile4(v1,v2,v3,v4)

    # 화면이 너무 크면 축소
    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)

    cv2.imshow(title, grid)

def show_gain_grid_centered(G1,G2,G3,G4, span=0.5, title="Gain"):
    def vis_center(g):
        g = g.astype(np.float32)
        v = (g - 1.0) / float(span)
        v = np.clip(v, -1.0, 1.0)
        v = (v * 0.5 + 0.5)
        return (v * 255.0 + 0.5).astype(np.uint8)

    g1 = cv2.cvtColor(vis_center(G1), cv2.COLOR_GRAY2BGR)
    g2 = cv2.cvtColor(vis_center(G2), cv2.COLOR_GRAY2BGR)
    g3 = cv2.cvtColor(vis_center(G3), cv2.COLOR_GRAY2BGR)
    g4 = cv2.cvtColor(vis_center(G4), cv2.COLOR_GRAY2BGR)

    cv2.putText(g1, "G1", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(g2, "G2", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(g3, "G3", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(g4, "G4", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)

    # 2x2 타일
    grid = tile4(g1,g2,g3,g4)

    # 화면이 너무 크면 축소
    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)

    cv2.imshow(title, grid)

def show_dB_grid_centered(G1,G2,G3,G4, span=0.5, title="dB"):
    def vis_signed(x, gain=8.0):
        v = np.clip(x * gain + 0.5, 0.0, 1.0)
        return (v * 255 + 0.5).astype(np.uint8)

    db1 = cv2.cvtColor(vis_signed(G1), cv2.COLOR_GRAY2BGR)
    db2 = cv2.cvtColor(vis_signed(G2), cv2.COLOR_GRAY2BGR)
    db3 = cv2.cvtColor(vis_signed(G3), cv2.COLOR_GRAY2BGR)
    db4 = cv2.cvtColor(vis_signed(G4), cv2.COLOR_GRAY2BGR)

    cv2.putText(db1, "dB1", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(db2, "dB2", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(db3, "dB3", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(db4, "dB4", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)

    # 2x2 타일
    grid = tile4(db1,db2,db3,db4)

    # 화면이 너무 크면 축소 (선택)
    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)

    cv2.imshow(title, grid)

def show_map_grid_centered(G1,G2,G3,G4, title="truth map"):
    g1 = cv2.cvtColor((G1 * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    g2 = cv2.cvtColor((G2 * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    g3 = cv2.cvtColor((G3 * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    g4 = cv2.cvtColor((G4 * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)

    cv2.putText(g1, "Y", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)    
    cv2.putText(g2, "E", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(g3, "C", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(g4, "N", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)

    # 2x2 타일
    grid = tile4(g1,g2,g3,g4)

    # 화면이 너무 크면 축소
    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)

    cv2.imshow(title, grid)

def yuv420_to_bgr_i420(y8: np.ndarray, u8: np.ndarray, v8: np.ndarray) -> np.ndarray:
    H, W = y8.shape
    # OpenCV expects a single 2D buffer: (H*3/2, W)
    yuv = np.empty((H * 3 // 2, W), dtype=np.uint8)
    yuv[0:H, :] = y8
    yuv[H:H + H // 4, :] = u8.reshape(H // 4, W)
    yuv[H + H // 4:H + H // 2, :] = v8.reshape(H // 4, W)

    bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)
    return bgr

def plot_line_profile(Y_in, Y_out, x=None, y=None, half_len=80, horizontal=True):
    H, W = Y_in.shape
    if x is None: x = W//2
    if y is None: y = H//2

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

    plt.figure(figsize=(10,4))
    plt.plot(axis, p_in,  label="Y_in")
    plt.plot(axis, p_out, label="Y_out")
    plt.title(f"Line profile @ ({x},{y})")
    plt.xlabel(xlabel); plt.ylabel("Y")
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend()
    plt.tight_layout()
    plt.show()

def find_failure_points_by_dY(Y_in, Y_out, C, c_thr=0.2, topk=10):
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

def sobel_dxdy(img: np.ndarray):
    img32 = img.astype(np.float32)
    dx = cv2.Sobel(img32, cv2.CV_32F, 1, 0, ksize=3)
    dy = cv2.Sobel(img32, cv2.CV_32F, 0, 1, ksize=3)
    return dx, dy

def sample_along_normal(dY: np.ndarray, nx: np.ndarray, ny: np.ndarray, L: int):
    """
    dY: (H,W) float32
    nx,ny: (H,W) float32 normal vectors (unit-ish)
    L: radius (samples from -L..+L, excluding 0 optional)
    returns:
      left_sum, right_sum, left_abs_sum, right_abs_sum (H,W) float32
    """
    H, W = dY.shape
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)

    left_sum  = np.zeros((H, W), np.float32)
    right_sum = np.zeros((H, W), np.float32)
    left_abs  = np.zeros((H, W), np.float32)
    right_abs = np.zeros((H, W), np.float32)

    # 샘플은 bilinear가 유리하니 remap 사용
    for t in range(1, L + 1):
        # left: -t, right: +t
        xl = xs - nx * t
        yl = ys - ny * t
        xr = xs + nx * t
        yr = ys + ny * t

        # remap expects map_x/map_y float32
        dl = cv2.remap(dY, xl, yl, interpolation=cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REFLECT101)
        dr = cv2.remap(dY, xr, yr, interpolation=cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REFLECT101)

        left_sum  += dl
        right_sum += dr
        left_abs  += np.abs(dl)
        right_abs += np.abs(dr)

    return left_sum, right_sum, left_abs, right_abs

def find_halo_points_by_edge_asymmetry(
    Y_in: np.ndarray,
    Y_out: np.ndarray,
    C: np.ndarray,
    c_thr: float = 0.2,
    L: int = 8,          # edge normal 방향 샘플 길이(halo tail 감지)
    topk: int = 20,
    ignore_border: int = 16,
    eps: float = 1e-6
):
    """
    Halo 후보점: edge에서 dY의 비대칭성이 큰 지점(white/black halo 또는 한쪽 꼬리)
    score 정의(직관):
      - asym = |(left_sum + right_sum)| / (left_abs + right_abs + eps)
        * 좌우가 대칭이면 left_sum ≈ -right_sum -> asym 작음
        * 한쪽만 바뀌면(left_sum, right_sum이 한쪽으로 치우침) asym 큼
      - strength = (left_abs + right_abs)
      - 최종 score = asym * strength * edge_mask
    """
    assert Y_in.shape == Y_out.shape
    H, W = Y_in.shape

    dY = (Y_out - Y_in).astype(np.float32)

    # edge normal: 입력의 gradient 방향 사용(구조 기준)
    dx, dy = sobel_dxdy(Y_in)
    mag = np.sqrt(dx*dx + dy*dy) + eps
    nx = dx / mag
    ny = dy / mag

    edge = (C > c_thr).astype(np.float32)

    # border는 신뢰 낮아서 제외
    if ignore_border > 0:
        edge[:ignore_border, :] = 0
        edge[-ignore_border:, :] = 0
        edge[:, :ignore_border] = 0
        edge[:, -ignore_border:] = 0

    left_sum, right_sum, left_abs, right_abs = sample_along_normal(dY, nx, ny, L=L)

    # 비대칭성(대칭이면 left_sum ~ -right_sum => left_sum+right_sum ~ 0)
    asym = np.abs(left_sum + right_sum) / (left_abs + right_abs + eps)

    # 변화량 자체가 너무 작은 곳은 의미 없으니 strength로 가중
    strength = (left_abs + right_abs)

    score = asym * strength * edge

    flat = score.reshape(-1)
    if topk >= flat.size:
        idxs = np.argsort(flat)[::-1]
    else:
        idxs = np.argpartition(flat, -topk)[-topk:]
        idxs = idxs[np.argsort(flat[idxs])[::-1]]

    pts = []
    for idx in idxs:
        if flat[idx] <= 0:
            continue
        y = idx // W
        x = idx % W
        pts.append((int(x), int(y), float(flat[idx])))

    # 디버깅용으로 score맵도 반환(선택)
    return pts, score

def show_halo_topk(
    bgr_in, bgr_out,
    Y_in, Y_out,
    C,
    c_thr=0.2,
    L=8,
    topk=10,
    r=60,
    zoom=5,
    diff_p=99.5,
    wait=0,
    title_prefix="HALO"
):
    pts, score_map = find_halo_points_by_edge_asymmetry(
        Y_in, Y_out, C,
        c_thr=c_thr, L=L, topk=topk
    )

    # pts는 (x,y,score) 형태인데, 네 show_failures_topk는 (x,y,v)로 받으니 그대로 사용 가능
    for i, (x, y, v) in enumerate(pts):
        show_zoom_compare_in_out_diff(
            bgr_in, bgr_out,
            Y_in, Y_out,
            x, y,
            r=r, zoom=zoom, diff_p=diff_p,
            title_prefix=f"{title_prefix} #{i+1} asymScore={v:.3e}"
        )
        print(f"[{title_prefix} {i+1}/{len(pts)}] (x={x}, y={y}) asymScore={v:.6e}")

        key = cv2.waitKey(wait) & 0xFF
        if key == 27:  # ESC
            break
        if key in (ord(' '), 13):  # space/enter
            continue

    return pts, score_map

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
    return pts

def crop_fixed(img, x, y, r=80):
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

def show_zoom_compare_in_out_diff(
    bgr_in, bgr_out,
    Y_in, Y_out,
    x, y,
    r=80,          # crop half size -> patch = (2r, 2r)
    zoom=4,        # 확대 배율
    diff_p=99.5,   # diff 시각화 스케일(퍼센타일)
    title_prefix="ZOOM"
):
    # --- crop (고정 크기 + padding)
    zin, _, _  = crop_fixed(bgr_in,  x, y, r=r)
    zout, _, _ = crop_fixed(bgr_out, x, y, r=r)

    # --- diff 1) RGB 차이(직관적)
    diff_bgr = cv2.absdiff(zin, zout)

    # --- diff 2) Y 차이(|dY|)를 더 잘 보이게(권장)
    dY = (Y_out - Y_in).astype(np.float32)
    dYc, _, _ = crop_fixed(dY, x, y, r=r)
    abs_dY = np.abs(dYc)

    s = np.percentile(np.abs(dY), diff_p) + 1e-8
    dY_norm = np.clip(abs_dY / s, 0.0, 1.0)
    dY_u8 = (dY_norm * 255.0 + 0.5).astype(np.uint8)

    # 컬러맵으로 보면 차이가 훨씬 잘 보임
    dY_heat = cv2.applyColorMap(dY_u8, cv2.COLORMAP_JET)

    # grad magnitude
    g_in  = grad_mag(Y_in)
    g_out = grad_mag(Y_out)

    ratio = (g_out + 1e-6) / (g_in + 1e-6)
    rc, _, _ = crop_fixed(ratio.astype(np.float32), x, y, r=r)

    # ratio -> [0,1] 로 매핑: 1.0이 0.5(중간), 1±span이 0/1
    rv = np.clip((rc - 1.0) / float(0.6), -1.0, 1.0)  # [-1,1]
    rv01 = (rv * 0.5 + 0.5)                                  # [0,1]
    ratio_u8 = (rv01 * 255.0 + 0.5).astype(np.uint8)

    # 컬러맵: 1.0(중간) 주변이 중간색, 강화/약화가 색으로 갈림
    ratio_heat = cv2.applyColorMap(ratio_u8, cv2.COLORMAP_JET)

    # --- 확대 (nearest가 디테일 비교에 유리)
    def up(img):
        h, w = img.shape[:2]
        return cv2.resize(img, (w*zoom, h*zoom), interpolation=cv2.INTER_NEAREST)

    zin_u   = up(zin)
    zout_u  = up(zout)
    diff_u  = up(diff_bgr)
    heat_u  = up(dY_heat)
    ratio_u  = up(ratio_heat)

    # --- 라벨
    def put_label(img, text):
        out = img.copy()
        cv2.putText(out, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,0,255), 2, cv2.LINE_AA)
        return out

    zin_u  = put_label(zin_u,  "IN")
    zout_u = put_label(zout_u, "OUT")
    diff_u = put_label(diff_u, "|IN-OUT| (BGR)")
    heat_u = put_label(heat_u, "|dY| heatmap")
    ratio_u = put_label(ratio_u, f"grad ratio heatmap")

    # --- 2줄짜리 그리드로 보여주자: (IN/OUT/DIFF) + (|dY| heatmap 크게)
    top = np.hstack([zin_u, zout_u, diff_u])
    bot = np.hstack([heat_u, ratio_u, ratio_u])  # heatmap을 넓게(가시성↑)

    grid = np.vstack([top, bot])

    cv2.imshow(f"{title_prefix} @ ({x},{y})", grid)

def show_failures_topk(bgr_in, bgr_out, Y_in, Y_out, pts, r=80, wait=0):
    for i, (x, y, v) in enumerate(pts):
        show_zoom_compare_in_out_diff(
            bgr_in, bgr_out, Y_in, Y_out,
            x, y,
            r=50, zoom=5, diff_p=99.5,
            title_prefix=f"{i+1} score={v:.3f}"
        )
        print(f"[zoom {i+1}/{len(pts)}] (x={x}, y={y}) score={v:.4f}")
        key = cv2.waitKey(wait) & 0xFF
        
        # ESC 누르면 중단
        if key == 27:
            break
        # 다음 후보로 강제 넘김: 스페이스/엔터도 허용
        if key in (ord(' '), 13):
            continue

# ============================================================
# 4-band decomposition + adaptive gain + pseudo-DR + fusion
# ============================================================
def multiband_pseudo_dr_y(
    Y: np.ndarray,
    r1: int = 8, r2: int = 24, r3: int = 64,
    eps_gf: float = 1e-3,
    sigma_E: float = 0.20,
    y_thr: float = 0.25,
    k1: float = 0.30,  # shadow lift
    k2: float = 0.10,  # halo damper
    k3: float = 0.25,  # edge contrast
    k4: float = 0.15,  # texture (noise-aware)
    smooth_gain: bool = True,
    gain_smooth_r: int = 8,
    gain_smooth_eps: float = 1e-3,
    tone_softclip: bool = True,
    softclip_strength: float = 0.85,
) -> np.ndarray:
    # --- decomposition (guided)
    base1 = guided_smooth(Y, r=r1, eps=eps_gf) # detail(엣지, 텍스처)
    base2 = guided_smooth(Y, r=r2, eps=eps_gf) # 중간 구조
    base3 = guided_smooth(Y, r=r3, eps=eps_gf) # 명암

    B1 = base3
    B2 = base2 - base3
    B3 = base1 - base2
    B4 = Y - base1

    # --- maps
    E, C, N = build_maps(Y, sigma_E=sigma_E, y_thr=y_thr)
    C = np.clip(C, 0.0, 1.0)

#    # --- gains (pseudo-DR)
#    G1 = 1.0 + k1 * (1.0 - E) * N         # shadow lift
#    G2 = 1.0 - k2 * C                     # halo damper
#    G3 = 1.0 + k3 * C * E                 # perceptual edge contrast
#    G4 = 1.0 + k4 * C * E * (1.0 - N)     # texture, avoid shadows

    # --- gains (pseudo-DR, adaptive)
    G1 = np.exp(k1 * (0.5 - E))           # shadow lift (B1)
    
    k2L = 0.85
    k2H = 0.15
    
    G2L = 1.0 + k2L * N * (0.3 + 0.7*(1.0 - E))     # shadow local lift (B2)
    G2H = 1.0 - k2H * C                              # halo damper
    G2  = G2L * G2H
    
    G3 = 1.0 + k3 * C * (0.5 + 0.5*E)               # edge contrast (B3)
    G4 = 1.0 + k4 * C * (0.5 + 0.5*E) * (1.0 - 0.5*N)  # texture (B4), less strict

    if smooth_gain:
        G1 = guided_filter_gray(Y, G1, r=gain_smooth_r, eps=gain_smooth_eps)
        G2 = guided_filter_gray(Y, G2, r=gain_smooth_r, eps=gain_smooth_eps)
        G3 = guided_filter_gray(Y, G3, r=gain_smooth_r, eps=gain_smooth_eps)
        G4 = guided_filter_gray(Y, G4, r=gain_smooth_r, eps=gain_smooth_eps)

    # safe clamp
    #G1 = np.clip(G1, 0.8, 1.8)
    #G2 = np.clip(G2, 0.7, 1.3)
    #G3 = np.clip(G3, 0.7, 1.6)
    #G4 = np.clip(G4, 0.5, 1.4)

    dB1 = (G1 - 1.0) * B1
    dB2 = (G2 - 1.0) * B2
    dB3 = (G3 - 1.0) * B3
    dB4 = (G4 - 1.0) * B4

    # --- show
    #show_bases_grid(Y, base1, base2, base3)
    #show_bands_grid(B1, B2, B3, B4)
    #show_map_grid_centered(Y, E, C, N)
    #show_dB_grid_centered(dB1, dB2, dB3, dB4, span=0.5)
    #show_gain_grid_centered(G1, G2, G3, G4, span=0.5)

    # --- multi-band fusion
    Y_out = G1 * B1 + G2 * B2 + G3 * B3 + G4 * B4

    # --- tone protect
    if tone_softclip:
        s = float(np.clip(softclip_strength, 0.2, 2.0))
        Y_out = Y_out / (Y_out + s * (1.0 - Y_out) + 1e-6)

    return Y_out.astype(np.float32), C

# ============================================================
# Main
# ============================================================
def main():
    #W, H = 228, 230
    #W, H = 1920, 1080
    #W, H = 1280, 720
    W, H = 1658, 1104
    
    #in_name = "./img/cat_nv12.img"
    #in_name = "./img/ch2_raw0.img"
    #in_name = "./img/ch0_raw0.img"
    in_name = "./img/scenary.img"

    out_name = "./img/output.img"

    base_dir = os.path.dirname(os.path.abspath(__file__))
    in_path = os.path.join(base_dir, in_name)
    out_path = os.path.join(base_dir, out_name)

    # -----------------------------
    # 1) Read input (NV12)
    #    y8: (H, W), uv: (H/2, W) interleaved
    # -----------------------------
    y8, uv = read_nv12_oneframe(in_path, W, H)
    Y = y8.astype(np.float32) / 255.0

    # -----------------------------
    # 2) ISP processing (Y only)
    # -----------------------------
    # -----------------------------
    # stable version
    # -----------------------------
    #Y_out, C = multiband_pseudo_dr_y(
    #    Y,
    #    r1=8, r2=24, r3=64,
    #    eps_gf=1e-3,
    #    sigma_E=0.20,
    #    y_thr=0.25,
    #    k1=0.30, k2=0.10, k3=0.25, k4=0.15,
    #    smooth_gain=True,
    #    tone_softclip=True,
    #)

    # -----------------------------
    # test
    # -----------------------------
    Y_out, C = multiband_pseudo_dr_y(
        Y,
        r1=8, r2=24, r3=64,
        eps_gf=1e-3,
        sigma_E=0.20,
        y_thr=0.35,
        k1=0.30, k2=0.10, k3=0.25, k4=0.15,
        smooth_gain=False,
        tone_softclip=False,
    )

    Y_out = np.clip(Y_out, 0.0, 1.0).astype(np.float32)
    y_out8 = (Y_out * 255.0 + 0.5).astype(np.uint8)

    #plot_line_profile(Y, Y_out, x=None, y=None, half_len=80, horizontal=True)
    #plot_line_profile(Y, Y_out, x=None, y=None, horizontal=False)

    D = Y_out - Y
    cv2.imshow("signed diff x8", (np.clip(D*8.0+0.5,0,1)*255).astype(np.uint8))

    # -----------------------------
    # 3) Write output (NV12 유지: Y_out + 원본 UV)
    # -----------------------------
    #write_nv12_oneframe(out_path, y_out8, uv)
    #print(f"OK: wrote {out_name} (NV12)")

    # -----------------------------
    # 4) OpenCV display (NV12 -> BGR)
    # -----------------------------

    # -----------------------------
    # toggle view
    # -----------------------------
    yuv_in  = np.vstack([y8, uv]).reshape((H * 3 // 2, W))
    yuv_out = np.vstack([y_out8, uv]).reshape((H * 3 // 2, W))

    bgr_in  = cv2.cvtColor(yuv_in,  cv2.COLOR_YUV2BGR_NV12)
    bgr_out = cv2.cvtColor(yuv_out, cv2.COLOR_YUV2BGR_NV12)

    # 1) 실패 후보점 자동 탐색 (dY 기반)
    pts_dy = find_failure_points_by_dY(Y, Y_out, C, c_thr=0.2, topk=5)

    # 2) 실패 후보점 자동 탐색 (gradient ratio 기반)
    pts_gr = find_failure_points_by_grad_ratio(Y, Y_out, C, c_thr=0.2, topk=5)
    pts_gr = [
        (1102, 499, 2.0054),
        (1098, 498, 1.9675),
        (1103, 501, 1.9518),
        (1102, 504, 1.9333),
        (1148, 440, 1.9241),
    ]
#    # 3) 후보점들 확대해서 보기 (dY 기준 top-k)
#    show_failures_topk(bgr_in, bgr_out, Y, Y_out, pts_dy, r=120, wait=0)
#
#    # 4) 후보점들 확대해서 보기 (grad-ratio 기준 top-k)
#    show_failures_topk(bgr_in, bgr_out, Y, Y_out, pts_gr, r=120, wait=0)
#
#    cv2.waitKey(0)

#    def draw_label(img: np.ndarray, text: str) -> np.ndarray:
#        """좌상단 라벨 오버레이 (원본 보호 위해 copy)"""
#        out = img.copy()
#        # 텍스트
#        cv2.putText(out, text, (20, 55),
#                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3, cv2.LINE_AA)
#        return out
#
#    win = "NV12 Toggle (1: toggle, 0: quit)"
#    show_output = False  # False=input, True=output
#
#    while True:
#        frame = bgr_out if show_output else bgr_in
#        label = "OUTPUT" if show_output else "INPUT"
#        frame_labeled = draw_label(frame, label)
#
#        # 화면이 너무 크면 축소
#        max_width = 1600
#        hh, ww = frame_labeled.shape[:2]
#        if ww > max_width:
#            scale = max_width / ww
#            disp = cv2.resize(frame_labeled, (int(ww * scale), int(hh * scale)), interpolation=cv2.INTER_AREA)
#        else:
#            disp = frame_labeled
#
#        cv2.imshow(win, disp)
#
#        key = cv2.waitKey(0) & 0xFF
#        if key == ord('1'):
#            show_output = not show_output
#        elif key == ord('0'):
#            break
    
    # guided 결과
    pts_g, score_g = show_halo_topk(
        bgr_in, bgr_out,
        Y, Y_out,
        C,
        c_thr=0.2, L=8, topk=1,
        r=40, zoom=5, diff_p=99.5,
        wait=0,
        title_prefix="GUIDED_HALO"
    )

    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()

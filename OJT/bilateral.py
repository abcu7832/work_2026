import os
import numpy as np
import cv2

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
# Bilateral multi-scale decomposition -> 4 bands
# ============================================================
def bilateral_smooth(Y: np.ndarray, sigma_s: float, sigma_r: float, d: int = -1) -> np.ndarray:
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
    # sigma_s: 공간적 범위, sigma_r 밝기 유사도 범위
    base1 = bilateral_smooth(Y, sigma_s=s1, sigma_r=r1)
    base2 = bilateral_smooth(Y, sigma_s=s2, sigma_r=r2)
    base3 = bilateral_smooth(Y, sigma_s=s3, sigma_r=r3)

    B1 = base3
    B2 = base2 - base3
    B3 = base1 - base2
    B4 = Y - base1
    return base1, base2, base3, (B1, B2, B3, B4)

# ============================================================
# Basic utils
# ============================================================
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
    C = np.clip((C - floor) / (1.0 - floor), 0.0, 1.0)
    C = C ** gamma
    return C.astype(np.float32)

def build_maps(Y: np.ndarray, sigma_E: float = 0.20, y_thr: float = 0.25):
    # well-exposedness (mid-tone reliability)
    E = np.exp(-((Y - 0.5) ** 2) / (2 * sigma_E * sigma_E)).astype(np.float32)

    # contrast/structure reliability
    C = build_C_robust(Y).astype(np.float32)

    # shadow mask (often used as noise-risk / shadow mask)
    N = np.clip((y_thr - Y) / max(y_thr, 1e-6), 0.0, 1.0).astype(np.float32)
    return E, C, N

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
    G1 = np.exp(k1 * (0.5 - E))           # shadow lift (B1)
    
    k2L = 0.80
    k2H = 0.15
    
    G2L = 1.0 + k2L * N * (0.3 + 0.7*(1.0 - E))     # shadow local lift (B2)
    G2H = 1.0 - k2H * C                              # halo damper
    G2  = G2L * G2H
    
    G3 = 1.0 + k3 * C * (0.5 + 0.5*E)               # edge contrast (B3)
    G4 = 1.0 + k4 * C * (0.5 + 0.5*E) * (1.0 - 0.5*N)  # texture (B4), less strict
    
    # --- delta bands (for debug)
    dB1 = (G1 - 1.0) * B1
    dB2 = (G2 - 1.0) * B2
    dB3 = (G3 - 1.0) * B3
    dB4 = (G4 - 1.0) * B4

    # --- fusion
    Y_out = (G1 * B1 + G2 * B2 + G3 * B3 + G4 * B4).astype(np.float32)

    # keep in [0,1]
    Y_out = np.clip(Y_out, 0.0, 1.0).astype(np.float32)

    # --- debug windows
    #show_bases_grid(Y, base1, base2, base3)
    #show_bands_grid(B1, B2, B3, B4)
    #show_maps_grid(Y, E, C1, N)
    #show_gain_grid_centered(G1, G2, G3, G4, span=0.5)
    #show_db_grid(dB1, dB2, dB3, dB4)

    return Y_out, (E, C1, N)

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

    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)
    cv2.imshow(title, grid)

def show_bands_grid(B1, B2, B3, B4, title="Bands (B1~B4)"):
    v1 = label_gray(to_uint8_01(B1), "B1")
    v2 = label_gray(vis_signed_auto(B2), "B2")
    v3 = label_gray(vis_signed_auto(B3), "B3")
    v4 = label_gray(vis_signed_auto(B4), "B4")
    top = np.hstack([v1, v2])
    bot = np.hstack([v3, v4])
    grid = np.vstack([top, bot])

    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)
    cv2.imshow(title, grid)

def show_maps_grid(Y, E, C, N, title="Maps (E/C/N/zero)"):
    e = label_gray(to_uint8_01(E), "E")
    c = label_gray(to_uint8_01(C), "C")
    n = label_gray(to_uint8_01(N), "N")
    z = label_gray(to_uint8_01(Y), "Y")
    top = np.hstack([z, e])
    bot = np.hstack([c, n])
    grid = np.vstack([top, bot])

    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)
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

    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)
    cv2.imshow(title, grid)

def show_db_grid(dB1, dB2, dB3, dB4, title="dB = (G-1)*B (auto)"):
    v1 = label_gray(vis_signed_auto(dB1), "dB1")
    v2 = label_gray(vis_signed_auto(dB2), "dB2")
    v3 = label_gray(vis_signed_auto(dB3), "dB3")
    v4 = label_gray(vis_signed_auto(dB4), "dB4")
    top = np.hstack([v1, v2])
    bot = np.hstack([v3, v4])
    grid = np.vstack([top, bot])

    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)
    cv2.imshow(title, grid)

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

def show_failures_topk(bgr_in, bgr_out, Y_in, Y_out, C, pts, r=80, wait=0):
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

# ============================================================
# Main
# ============================================================
def main():
    # ---------- Set your NV12 size / paths ----------
    W, H = 1658, 1104
    #W, H = 762, 506
    #W, H = 1920, 1080
    in_name  = "./img/scenary.img"   # NV12 file
    #in_name  = "./img/scenary2.img"   # NV12 file
    #in_name = "./img/ch2_raw0.img"
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
    )

    y_out8 = (Y_out * 255.0 + 0.5).astype(np.uint8)

    yuv_in  = np.vstack([y8, uv]).reshape((H * 3 // 2, W))
    yuv_out = np.vstack([y_out8, uv]).reshape((H * 3 // 2, W))

    bgr_in  = cv2.cvtColor(yuv_in,  cv2.COLOR_YUV2BGR_NV12)
    bgr_out = cv2.cvtColor(yuv_out, cv2.COLOR_YUV2BGR_NV12)

    # ---------- Write output (NV12: keep UV) ----------
    write_nv12_oneframe(out_path, y_out8, uv)

    # 1) 실패 후보점 자동 탐색 (dY 기반)
    #pts_dy = find_failure_points_by_dY(Y, Y_out, C, c_thr=0.2, topk=5)

    # 2) 실패 후보점 자동 탐색 (gradient ratio 기반)
    #pts_gr, ratio = find_failure_points_by_grad_ratio(Y, Y_out, C, c_thr=0.2, topk=5)

    # 3) 후보점들 확대해서 보기 (dY 기준 top-k)
    #show_failures_topk(bgr_in, bgr_out, Y, Y_out, C, pts_dy, r=120, wait=0)

    # 4) 후보점들 확대해서 보기 (grad-ratio 기준 top-k)
    #show_failures_topk(bgr_in, bgr_out, Y, Y_out, C, pts_gr, r=120, wait=0)

    # bilateral 결과
    pts_b, score_b = show_halo_topk(
        bgr_in, bgr_out,
        Y, Y_out,
        C,
        c_thr=0.2, L=8, topk=1,
        r=40, zoom=5, diff_p=99.5,
        wait=0,
        title_prefix="BILATERAL_HALO"
    )

    D = Y_out - Y
    cv2.imshow("signed b diff x8", (np.clip(D*8.0+0.5,0,1)*255).astype(np.uint8))

    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()

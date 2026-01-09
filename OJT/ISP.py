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

    # 활성 면적 과다 방지(옵션): 상위 20%만 살리기
    # t = np.percentile(C, 80.0)
    # C = np.clip((C - t) / (1.0 - t + 1e-6), 0.0, 1.0)

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
# 4-band decomposition + adaptive gain + pseudo-DR + fusion
# ============================================================
def band_to_vis8(band: np.ndarray, scale: float) -> np.ndarray:
    """
    band (float32) 를 시각화용 8-bit 이미지로 변환.
    - band는 대체로 0 중심(양/음)을 가지므로 0을 회색(0.5)로 매핑
    - scale로 증폭해서 보기 쉽게 함
    """
    vis = band.astype(np.float32) * float(scale)
    vis = np.clip(vis + 0.5, 0.0, 1.0)            # 0 -> 0.5(회색)
    return (vis * 255.0 + 0.5).astype(np.uint8)

def put_label(gray8: np.ndarray, text: str) -> np.ndarray:
    """단일 채널 8-bit 이미지에 라벨을 넣고 3채널(BGR)로 변환"""
    bgr = cv2.cvtColor(gray8, cv2.COLOR_GRAY2BGR)

    red = (0, 0, 255)
    fontScale = 1.5

    cv2.putText(bgr, text, (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX, fontScale, red, 2, cv2.LINE_AA)

    return bgr

def to_uint8_01(x: np.ndarray) -> np.ndarray:
    """float [0..1] -> uint8"""
    x = np.clip(x.astype(np.float32), 0.0, 1.0)
    return (x * 255.0 + 0.5).astype(np.uint8)

def label_gray(gray8: np.ndarray, text: str) -> np.ndarray:
    """1채널 uint8 -> BGR로 바꾸고 라벨 표시"""
    bgr = cv2.cvtColor(gray8, cv2.COLOR_GRAY2BGR)
    cv2.putText(bgr, text, (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2, cv2.LINE_AA)
    return bgr

def show_bases_grid(Y: np.ndarray, base1: np.ndarray, base2: np.ndarray, base3: np.ndarray,
                    title="Bases (Y, base1, base2, base3)"):
    yv  = label_gray(to_uint8_01(Y),     "Y(input)")
    b1v = label_gray(to_uint8_01(base1), "base1")
    b2v = label_gray(to_uint8_01(base2), "base2")
    b3v = label_gray(to_uint8_01(base3), "base3")

    top = np.hstack([yv, b1v])
    bot = np.hstack([b2v, b3v])
    grid = np.vstack([top, bot])

    # 너무 크면 축소
    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        s = max_width / w
        grid = cv2.resize(grid, (int(w*s), int(h*s)), interpolation=cv2.INTER_AREA)

    cv2.imshow(title, grid)

    
def show_bands_grid(B1, B2, B3, B4, title="Bands (2x2)"):
    """
    B1~B4를 2x2로 붙여서 한 창에 표시
    """
    # 시각화 스케일(필요하면 조절)
    v1 = put_label(band_to_vis8(B1, scale=1.0),  "B1")
    v2 = put_label(band_to_vis8(B2, scale=4.0),  "B2")
    v3 = put_label(band_to_vis8(B3, scale=8.0),  "B3")
    v4 = put_label(band_to_vis8(B4, scale=16.0), "B4")

    # 2x2 타일
    top = np.hstack([v1, v2])
    bot = np.hstack([v3, v4])
    grid = np.vstack([top, bot])

    # 화면이 너무 크면 축소 (선택)
    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)

    cv2.imshow(title, grid)

def tile4(a,b,c,d):
    return np.vstack([np.hstack([a,b]), np.hstack([c,d])])

def show_gain_grid_centered(G1,G2,G3,G4, span=0.5, title="Gain Grid"):
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
    top = np.hstack([g1, g2])
    bot = np.hstack([g3, g4])
    grid = np.vstack([top, bot])

    # 화면이 너무 크면 축소 (선택)
    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)

    cv2.imshow(title, grid)

def show_dB_grid_centered(G1,G2,G3,G4, span=0.5, title="dB Grid"):
    def vis_signed(x, gain=8.0):
        v = np.clip(x * gain + 0.5, 0.0, 1.0)
        return (v * 255 + 0.5).astype(np.uint8)

    g1 = cv2.cvtColor(vis_signed(G1), cv2.COLOR_GRAY2BGR)
    g2 = cv2.cvtColor(vis_signed(G2), cv2.COLOR_GRAY2BGR)
    g3 = cv2.cvtColor(vis_signed(G3), cv2.COLOR_GRAY2BGR)
    g4 = cv2.cvtColor(vis_signed(G4), cv2.COLOR_GRAY2BGR)

    cv2.putText(g1, "dB1", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(g2, "dB2", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(g3, "dB3", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(g4, "dB4", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)

    # 2x2 타일
    top = np.hstack([g1, g2])
    bot = np.hstack([g3, g4])
    grid = np.vstack([top, bot])

    # 화면이 너무 크면 축소 (선택)
    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)

    cv2.imshow(title, grid)

def show_map_grid_centered(G1,G2,G3,G4, title="truth map Grid"):
    g1 = cv2.cvtColor((G1 * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    g2 = cv2.cvtColor((G2 * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    g3 = cv2.cvtColor((G3 * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    g4 = cv2.cvtColor((G4 * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)

    cv2.putText(g1, "Y", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)    
    cv2.putText(g2, "E", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(g3, "C", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)
    cv2.putText(g4, "N", (20,40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,255), 2)

    # 2x2 타일
    top = np.hstack([g1, g2])
    bot = np.hstack([g3, g4])
    grid = np.vstack([top, bot])

    # 화면이 너무 크면 축소 (선택)
    max_width = 1600
    h, w = grid.shape[:2]
    if w > max_width:
        scale = max_width / w
        grid = cv2.resize(grid, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)

    cv2.imshow(title, grid)

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

    show_bases_grid(Y, base1, base2, base3)

    # --- BAND visualize
    show_bands_grid(B1, B2, B3, B4)
    #cv2.waitKey(0)

    # --- maps
    E, C, N = build_maps(Y, sigma_E=sigma_E, y_thr=y_thr)

    #cv2.imshow("E", (E * 255).astype(np.uint8))
    #cv2.imshow("C", (C * 255).astype(np.uint8))
    #cv2.imshow("N", (N * 255).astype(np.uint8))
    show_map_grid_centered(Y, E, C, N)

    # --- gains (pseudo-DR)
    G1 = 1.0 + k1 * (1.0 - E) * N         # shadow lift
    G2 = 1.0 - k2 * C                     # halo damper
    G3 = 1.0 + k3 * C * E                 # perceptual edge contrast
    G4 = 1.0 + k4 * C * E * (1.0 - N)     # texture, avoid shadows

    # --- gains (pseudo-DR, adaptive)
    G1 = np.exp(k1 * (0.5 - E))           # shadow lift (B1)
    
    k2L = 0.80   # <-- 추가 파라미터로 빼도 됨
    k2H = 0.15   # <-- 기존 k2 대신 분리 추천
    
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

    print("G1 min/max:", G1.min(), G1.max())
    print("G2 min/max:", G2.min(), G2.max())
    print("G3 min/max:", G3.min(), G3.max())
    print("G4 min/max:", G4.min(), G4.max())

    # safe clamp
    #G1 = np.clip(G1, 0.8, 1.8)
    #G2 = np.clip(G2, 0.7, 1.3)
    #G3 = np.clip(G3, 0.7, 1.6)
    #G4 = np.clip(G4, 0.5, 1.4)

    dB1 = (G1 - 1.0) * B1
    dB2 = (G2 - 1.0) * B2
    dB3 = (G3 - 1.0) * B3
    dB4 = (G4 - 1.0) * B4

    def stat(name, x):
        ax = np.abs(x)
        print(f"{name}: mean(abs)={ax.mean():.6g}, max(abs)={ax.max():.6g}, min={x.min():.6g}, max={x.max():.6g}")

    stat("B2", B2); stat("B3", B3); stat("B4", B4)
    stat("G2-1", G2-1); stat("G3-1", G3-1); stat("G4-1", G4-1)
    stat("dB2", dB2); stat("dB3", dB3); stat("dB4", dB4)

    show_dB_grid_centered(dB1, dB2, dB3, dB4, span=0.5)

#    def vis_signed(x, gain=8.0):
#        v = np.clip(x * gain + 0.5, 0.0, 1.0)
#        return (v * 255 + 0.5).astype(np.uint8)
#    cv2.imshow("dB1", vis_signed(dB1, 8))
#    cv2.imshow("dB2", vis_signed(dB2, 8))
#    cv2.imshow("dB3", vis_signed(dB3, 8))
#    cv2.imshow("dB4", vis_signed(dB4, 8))    

    show_gain_grid_centered(G1, G2, G3, G4, span=0.5)
    #cv2.waitKey(0)

    # --- multi-band fusion
    Y_out = G1 * B1 + G2 * B2 + G3 * B3 + G4 * B4

    # --- tone protect
    if tone_softclip:
        s = float(np.clip(softclip_strength, 0.2, 2.0))
        Y_out = Y_out / (Y_out + s * (1.0 - Y_out) + 1e-6)

    #return np.clip(Y_out, 0.0, 1.0).astype(np.float32)
    return Y_out.astype(np.float32)

def yuv420_to_bgr_i420(y8: np.ndarray, u8: np.ndarray, v8: np.ndarray) -> np.ndarray:
    # rgb로 보기    
    """
    y8: HxW
    u8: H/2 x W/2
    v8: H/2 x W/2
    return: BGR HxW (uint8)
    """
    H, W = y8.shape
    # OpenCV expects a single 2D buffer: (H*3/2, W)
    yuv = np.empty((H * 3 // 2, W), dtype=np.uint8)
    yuv[0:H, :] = y8
    yuv[H:H + H // 4, :] = u8.reshape(H // 4, W)
    yuv[H + H // 4:H + H // 2, :] = v8.reshape(H // 4, W)

    bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)
    return bgr

def show_side_by_side(title: str, bgr_left: np.ndarray, bgr_right: np.ndarray, max_width: int = 1600):
    """
    두 이미지를 좌/우로 붙여서 보여줌. 화면이 너무 크면 축소.
    """
    H1, W1 = bgr_left.shape[:2]
    H2, W2 = bgr_right.shape[:2]
    assert (H1 == H2), "Heights must match for side-by-side view."

    vis = np.hstack([bgr_left, bgr_right])

    H, W = vis.shape[:2]
    if W > max_width:
        scale = max_width / W
        vis = cv2.resize(vis, (int(W * scale), int(H * scale)), interpolation=cv2.INTER_AREA)

    cv2.imshow(title, vis)

def plot_line_profile(Y_in, Y_out, x=None, y=None, half_len=80, horizontal=True):
    H, W = Y_in.shape
    if x is None: x = W//2
    if y is None: y = H//2

    if horizontal:
        x0 = max(0, x-half_len); x1 = min(W, x+half_len)
        p_in  = Y_in[y, x0:x1]
        p_out = Y_out[y, x0:x1]
        axis = np.arange(x0, x1)
        xlabel = "axis_index"
    else:
        y0 = max(0, y-half_len); y1 = min(H, y+half_len)
        p_in  = Y_in[y0:y1, x]
        p_out = Y_out[y0:y1, x]
        axis = np.arange(y0, y1)
        xlabel = "y"

    plt.figure(figsize=(10,4))
    plt.plot(axis, p_in,  label="Y_in")
    plt.plot(axis, p_out, label="Y_out")
    plt.title(f"Line profile @ ({x},{y})")
    plt.xlabel(xlabel); plt.ylabel("Y")
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend()
    plt.tight_layout()
    plt.show()

# ============================================================
# Main
# ============================================================
def main():
    #W, H = 1920, 1080
    #W, H = 1280, 720
    #W, H = 228, 230
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
    #Y_out = multiband_pseudo_dr_y(
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
    Y_out = multiband_pseudo_dr_y(
        Y,
        r1=8, r2=24, r3=64,
        eps_gf=1e-3,
        sigma_E=0.20,
        y_thr=0.35,
        k1=0.30, k2=0.10, k3=0.25, k4=0.15,
        smooth_gain=True,
        tone_softclip=False,
    )

    Y_out = np.clip(Y_out, 0.0, 1.0).astype(np.float32)
    y_out8 = (Y_out * 255.0 + 0.5).astype(np.uint8)

    # -----------------------------
    # 3) Write output (NV12 유지: Y_out + 원본 UV)
    # -----------------------------
    write_nv12_oneframe(out_path, y_out8, uv)
    print(f"OK: wrote {out_name} (NV12)")

    # -----------------------------
    # 4) OpenCV display (NV12 -> BGR)
    # -----------------------------
    # OpenCV는 (H*3/2, W) 형태의 NV12 버퍼를 기대함

    # -----------------------------
    # inout 좌우 window
    # -----------------------------
#    yuv_in = np.vstack([y8, uv]).reshape((H * 3 // 2, W))
#    yuv_out = np.vstack([y_out8, uv]).reshape((H * 3 // 2, W))
#
#    bgr_in = cv2.cvtColor(yuv_in, cv2.COLOR_YUV2BGR_NV12)
#    bgr_out = cv2.cvtColor(yuv_out, cv2.COLOR_YUV2BGR_NV12)
#
#    vis = np.hstack([bgr_in, bgr_out])
#
#    max_width = 1600
#    hh, ww = vis.shape[:2]
#    if ww > max_width:
#        scale = max_width / ww
#        vis = cv2.resize(vis, (int(ww * scale), int(hh * scale)), interpolation=cv2.INTER_AREA)
#
#    cv2.imshow("Input (Left) | Output (Right) [NV12]", vis)
#    cv2.imwrite(os.path.join(base_dir, "./out/input.png"), bgr_in)
#    cv2.imwrite(os.path.join(base_dir, "./out/output.png"), bgr_out)
#
#    print("Press any key to exit...")
#    cv2.waitKey(0)
#    cv2.destroyAllWindows()
    
    plot_line_profile(Y, Y_out, x=None, y=None, half_len=80, horizontal=True)

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

if __name__ == "__main__":
    main()

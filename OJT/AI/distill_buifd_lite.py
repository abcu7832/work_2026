import os, glob, time, argparse
import numpy as np
import cv2

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

# -----------------------------
# common utils
# -----------------------------
def ensure_dir(d):
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)

def strip_module_prefix(sd):
    return {k.replace("module.", ""): v for k, v in sd.items()}

def load_sd_any(path):
    ckpt = torch.load(path, map_location="cpu")
    sd = ckpt["state_dict"] if isinstance(ckpt, dict) and "state_dict" in ckpt else ckpt
    return strip_module_prefix(sd)

def psnr_torch(a, b, eps=1e-12):
    # a,b: BCHW in [0,1]
    mse = torch.mean((a - b) ** 2, dim=(1,2,3)).clamp_min(eps)  # per-sample
    return 10.0 * torch.log10(1.0 / mse)

def save_rgb01_tensor_as_png(path, x_bchw):
    x = x_bchw.detach().float().cpu().clamp(0, 1)[0]
    x = x.permute(1, 2, 0).numpy()  # HWC RGB
    x = (x * 255.0 + 0.5).astype(np.uint8)
    x = cv2.cvtColor(x, cv2.COLOR_RGB2BGR)
    cv2.imwrite(path, x)

def parse_sigma_from_noisy_path(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    if "_sigma" in stem:
        try:
            return int(stem.split("_sigma", 1)[1])
        except Exception:
            return None
    return None


class SinglePairDataset(Dataset):
    def __init__(self, noisy_dir, clean_dir, resize_hw=None):
        self.noisy_dir = noisy_dir
        self.clean_dir = clean_dir
        self.resize_hw = resize_hw

        clean_paths = []
        for ext in ("png", "jpg", "jpeg", "PNG", "JPG", "JPEG"):
            clean_paths += glob.glob(os.path.join(clean_dir, f"*.{ext}"))
        if len(clean_paths) == 0:
            raise RuntimeError(f"No clean images in {clean_dir}")

        self.clean_map = {os.path.splitext(os.path.basename(p))[0]: p for p in clean_paths}

        noisy_paths = sorted(glob.glob(os.path.join(noisy_dir, "*.png")))
        if len(noisy_paths) == 0:
            raise RuntimeError(f"No noisy png in {noisy_dir}")

        pairs = []
        miss = 0
        for n in noisy_paths:
            stem = os.path.splitext(os.path.basename(n))[0]   # 2018_sigma25
            key = stem.split("_sigma", 1)[0] if "_sigma" in stem else stem
            c = self.clean_map.get(key, None)
            if c is not None:
                sigma = parse_sigma_from_noisy_path(n)
                pairs.append((n, c, sigma))
            else:
                miss += 1

        if len(pairs) == 0:
            raise RuntimeError("No matched pairs (check naming)")

        self.pairs = pairs
        # sigma coverage print
        sigmas = sorted({p[2] for p in self.pairs if p[2] is not None})
        print(f"[SinglePairDataset] matched={len(self.pairs)} miss={miss} sigmas={sigmas}")

    def __len__(self):
        return len(self.pairs)

    def _read_rgb01(self, path):
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(path)

        if self.resize_hw is not None:
            h, w = self.resize_hw
            if (img.shape[0], img.shape[1]) != (h, w):
                img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)

        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        x = torch.from_numpy(img).float() / 255.0  # 0..1
        return x.permute(2, 0, 1)                  # CHW

    def __getitem__(self, i):
        n, c, sigma = self.pairs[i]
        return self._read_rgb01(n), self._read_rgb01(c), n, sigma


def max_index_for_prefix(keys, prefix):
    import re
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)\.")
    mx = -1
    for k in keys:
        m = pat.match(k)
        if m:
            mx = max(mx, int(m.group(1)))
    if mx < 0:
        raise RuntimeError(f"No keys for prefix={prefix}")
    return mx

def build_seq_from_sd(sd, prefix, relu_in_missing=True):
    keys = sd.keys()
    mx = max_index_for_prefix(keys, prefix)
    mods = []
    for i in range(mx + 1):
        w_key = f"{prefix}{i}.weight"
        b_key = f"{prefix}{i}.bias"
        rm_key = f"{prefix}{i}.running_mean"
        rv_key = f"{prefix}{i}.running_var"
        nbt_key = f"{prefix}{i}.num_batches_tracked"

        if w_key in sd:
            w = sd[w_key]
            if w.ndim == 4:
                Cout, Cin, kH, kW = w.shape
                pad = (kW // 2, kH // 2)
                bias = b_key in sd
                mods.append(nn.Conv2d(Cin, Cout, (kH, kW), 1, pad, bias=bias))
                continue
            if w.ndim == 1:
                C = int(w.numel())
                mods.append(nn.BatchNorm2d(C, affine=True))
                continue
            raise RuntimeError(f"Unexpected {w_key} shape {tuple(w.shape)}")

        if (rm_key in sd) or (rv_key in sd) or (nbt_key in sd):
            C = int(sd[rm_key].numel() if rm_key in sd else sd[rv_key].numel())
            mods.append(nn.BatchNorm2d(C, affine=True))
            continue

        mods.append(nn.ReLU(inplace=True) if relu_in_missing else nn.Identity())

    return nn.Sequential(*mods)

class FusionLayers(nn.Module):
    def __init__(self, sd, prefix="FusionLayers.fusion_layers."):
        super().__init__()

        def mk(idx):
            w = sd[f"{prefix}{idx}.weight"]
            b = f"{prefix}{idx}.bias" in sd
            Cout, Cin, kH, kW = w.shape
            pad = (kW // 2, kH // 2)
            return nn.Conv2d(Cin, Cout, (kH, kW), 1, pad, bias=b)

        self.fusion_layers = nn.Sequential(mk(0), mk(1), mk(2))

    def forward(self, x):
        return self.fusion_layers(x)

class BUIFD_FusionTeacher(nn.Module):
    def __init__(self, sd):
        super().__init__()
        self.dncnn = nn.Module()
        self.dncnn.dncnn = build_seq_from_sd(sd, "dncnn.dncnn.")
        self.noisecnn = nn.Module()
        self.noisecnn.noisecnn = build_seq_from_sd(sd, "noisecnn.noisecnn.")
        self.FusionLayers = FusionLayers(sd, "FusionLayers.fusion_layers.")
        self.sigmoid = nn.Sigmoid()

        w0 = sd["FusionLayers.fusion_layers.0.weight"]
        assert w0.shape[1] == 15, f"Expected fusion input 15ch, got {w0.shape[1]}"

    def forward(self, x):
        noise = self.dncnn.dncnn(x)            # noise (residual)
        prior = x - noise                      # denoised prior

        nl_raw = self.noisecnn.noisecnn(x)     # raw noise level
        noise_level = self.sigmoid(nl_raw)     # IMPORTANT: sigmoid

        x_cat = torch.cat([
            x,
            prior,
            noise_level,
            x * (1.0 - noise_level),
            prior * noise_level
        ], dim=1)

        denoised = self.FusionLayers(x_cat)
        noise_out = x - denoised

        return noise_out, noise_level


# -----------------------------
# Student: BUIFD-lite (denoised output)
# -----------------------------
class DnCNN_Lite(nn.Module):
    def __init__(self, channels=3, features=48, num_layers=12, use_bn=True):
        super().__init__()
        assert num_layers >= 3
        ks, pad = 3, 1
        layers = [
            nn.Conv2d(channels, features, ks, padding=pad, bias=True),
            nn.ReLU(inplace=True),
        ]
        for _ in range(num_layers - 2):
            layers.append(nn.Conv2d(features, features, ks, padding=pad, bias=True))
            if use_bn:
                layers.append(nn.BatchNorm2d(features))
            layers.append(nn.ReLU(inplace=True))
        layers.append(nn.Conv2d(features, channels, ks, padding=pad, bias=True))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)

class NoiseCNN_Lite(nn.Module):
    def __init__(self, channels=3, features=48, num_layers=4, use_bn=True):
        super().__init__()
        ks, pad = 5, 2
        layers = [
            nn.Conv2d(channels, features, ks, padding=pad, bias=True),
            nn.ReLU(inplace=True),
        ]
        for _ in range(num_layers):
            layers.append(nn.Conv2d(features, features, ks, padding=pad, bias=True))
            if use_bn:
                layers.append(nn.BatchNorm2d(features))
            layers.append(nn.ReLU(inplace=True))
        layers.append(nn.Conv2d(features, channels, ks, padding=pad, bias=True))
        self.net = nn.Sequential(*layers)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        return self.sigmoid(self.net(x))

class FusionLite(nn.Module):
    def __init__(self, channels=3, features=16):
        super().__init__()
        self.fuse = nn.Sequential(
            nn.Conv2d(5*channels, features, 3, padding=1, bias=True),
            nn.Conv2d(features, features, 3, padding=1, bias=True),
            nn.Conv2d(features, channels, 3, padding=1, bias=True),
        )

    def forward(self, x_cat):
        return self.fuse(x_cat)

class BUIFD_Lite_Denoised(nn.Module):
    def __init__(self, channels=3,
                 dn_features=48, dn_layers=12,
                 ns_features=48, ns_layers=4,
                 fuse_features=16,
                 use_bn=True):
        super().__init__()
        self.dncnn = DnCNN_Lite(channels, dn_features, dn_layers, use_bn=use_bn)
        self.noisecnn = NoiseCNN_Lite(channels, ns_features, ns_layers, use_bn=use_bn)
        self.fusion = FusionLite(channels, fuse_features)

    def forward(self, x):
        dn = self.dncnn(x)
        prior = x - dn
        nl = self.noisecnn(x)
        x_cat = torch.cat([x, prior, nl, x*(1-nl), prior*nl], dim=1)
        den = self.fusion(x_cat)
        return den


# -----------------------------
# evaluation: per-sigma + overall mean
# -----------------------------
@torch.no_grad()
def evaluate_by_sigma(student, teacher, dl_eval, device, use_amp=False):
    student.eval()
    teacher.eval()

    sum_psnr = {}
    cnt_psnr = {}

    for noisy, clean, _p, sigma in dl_eval:
        noisy = noisy.to(device, non_blocking=True)
        clean = clean.to(device, non_blocking=True)

        # teacher denoised
        noise_out_t, _ = teacher(noisy)
        den_t = (noisy - noise_out_t).clamp(0, 1)

        with torch.amp.autocast("cuda", enabled=use_amp and device == "cuda"):
            den_s = student(noisy).clamp(0, 1)

        ps = psnr_torch(den_s, clean)

        sigma = sigma.cpu().numpy().tolist()
        ps = ps.detach().float().cpu().numpy().tolist()

        for s, p in zip(sigma, ps):
            s = int(s) if s is not None else -1
            sum_psnr[s] = sum_psnr.get(s, 0.0) + float(p)
            cnt_psnr[s] = cnt_psnr.get(s, 0) + 1

    # means
    mean_psnr = {s: (sum_psnr[s] / max(cnt_psnr[s], 1)) for s in sum_psnr.keys()}

    # overall mean over all samples (weighted)
    total_sum = 0.0
    total_cnt = 0
    for s in sum_psnr.keys():
        total_sum += sum_psnr[s]
        total_cnt += cnt_psnr[s]
    overall = total_sum / max(total_cnt, 1)

    return overall, mean_psnr, cnt_psnr


# -----------------------------
# run one experiment
# -----------------------------
def run_exp(exp_name, cfg, args, device):
    print(f"\n==================== {exp_name} ====================")
    print("[cfg]", cfg)

    # teacher
    sd_t = load_sd_any(args.teacher_ckpt)
    teacher = BUIFD_FusionTeacher(sd_t).to(device)
    teacher.load_state_dict(sd_t, strict=True)
    teacher.eval()
    for p in teacher.parameters():
        p.requires_grad_(False)
    print("[teacher] loaded strict=True OK")

    # student
    student = BUIFD_Lite_Denoised(
        channels=3,
        dn_features=cfg["dn_features"],
        dn_layers=cfg["dn_layers"],
        ns_features=cfg["ns_features"],
        ns_layers=cfg["ns_layers"],
        fuse_features=cfg.get("fuse_features", 16),
        use_bn=not args.no_bn,
    ).to(device)

    opt = torch.optim.Adam(student.parameters(), lr=args.lr)
    use_amp = bool(args.amp and device == "cuda")
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    # data
    ds = SinglePairDataset(args.noisy_dir, args.clean_dir, resize_hw=(args.H, args.W))

    dl_train = DataLoader(
        ds, batch_size=args.batch, shuffle=True,
        num_workers=args.num_workers, pin_memory=True,
        drop_last=True
    )
    dl_eval = DataLoader(
        ds, batch_size=args.eval_batch or args.batch, shuffle=False,
        num_workers=args.num_workers, pin_memory=True,
        drop_last=False
    )

    out_dir = os.path.join(args.out_dir, exp_name)
    ensure_dir(out_dir)

    best_overall = -1e9
    best_epoch = -1

    for ep in range(1, args.epochs + 1):
        t0 = time.time()
        student.train()

        run_loss = 0.0
        steps = 0

        for noisy, clean, _p, _sigma in dl_train:
            noisy = noisy.to(device, non_blocking=True)
            clean = clean.to(device, non_blocking=True)

            with torch.no_grad():
                noise_out_t, _noise_level_t = teacher(noisy)
                den_t = (noisy - noise_out_t).clamp(0, 1)

            opt.zero_grad(set_to_none=True)

            with torch.amp.autocast("cuda", enabled=use_amp):
                den_s = student(noisy)

                loss_clean = F.l1_loss(den_s, clean)
                loss_teacher = F.l1_loss(den_s, den_t)

                if args.w_res > 0:
                    res_s = noisy - den_s
                    res_t = noisy - den_t
                    loss_res = F.l1_loss(res_s, res_t)
                else:
                    loss_res = torch.zeros((), device=device)

                loss = args.w_clean * loss_clean + args.w_teacher * loss_teacher + args.w_res * loss_res

            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()

            run_loss += float(loss.detach().item())
            steps += 1

        avg_loss = run_loss / max(steps, 1)

        # --- EVAL: overall mean + per-sigma mean ---
        overall, mean_psnr, cnt_psnr = evaluate_by_sigma(student, teacher, dl_eval, device, use_amp=use_amp)

        print(f"[{exp_name}] ep {ep:03d}  train_loss {avg_loss:.6f}  EVAL_overall_psnr {overall:.3f} dB  time {time.time()-t0:.1f}s")

        # best by overall mean (5~55 mixed)
        if overall > best_overall:
            best_overall = overall
            best_epoch = ep
            pth_path = os.path.join(out_dir, f"{exp_name}_best.pth")
            torch.save(student.state_dict(), pth_path)
            print("[save best]", pth_path, "best_overall_psnr=", best_overall, "best_epoch=", best_epoch)

            # print all sigma psnrs (sorted). expect 5~55
            sigmas_sorted = sorted([s for s in mean_psnr.keys() if s != -1])
            msg = " | ".join([f"sigma{s}: {mean_psnr[s]:.3f}dB(n={cnt_psnr[s]})" for s in sigmas_sorted])
            print("[best per-sigma]", msg)

        if args.save_png:
            student.eval()
            with torch.no_grad():
                noisy0, clean0, _, _ = ds[0]
                noisy0 = noisy0.unsqueeze(0).to(device)
                clean0 = clean0.unsqueeze(0).to(device)

                noise_out0, _ = teacher(noisy0)
                den_t0 = (noisy0 - noise_out0).clamp(0, 1)

                den_s0 = student(noisy0).clamp(0, 1)

            save_rgb01_tensor_as_png(os.path.join(out_dir, f"ep{ep:03d}_noisy.png"), noisy0)
            save_rgb01_tensor_as_png(os.path.join(out_dir, f"ep{ep:03d}_clean.png"), clean0)
            save_rgb01_tensor_as_png(os.path.join(out_dir, f"ep{ep:03d}_teacher_denoised.png"), den_t0)
            save_rgb01_tensor_as_png(os.path.join(out_dir, f"ep{ep:03d}_student_denoised.png"), den_s0)

    # export ONNX from best
    pth_path = os.path.join(out_dir, f"{exp_name}_best.pth")
    if os.path.isfile(pth_path):
        student.load_state_dict(torch.load(pth_path, map_location="cpu"), strict=True)

    student.eval().to(device)
    dummy = torch.randn(1, 3, args.H, args.W, device=device)
    onnx_path = os.path.join(out_dir, f"{exp_name}_best.onnx")
    torch.onnx.export(
        student, dummy, onnx_path,
        opset_version=13,
        input_names=["input"],
        output_names=["denoised"],
        do_constant_folding=True,
        dynamic_axes=None,
    )
    print("[export]", onnx_path)
    print(f"[{exp_name}] DONE. best_overall_psnr={best_overall:.3f} dB (epoch {best_epoch})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher_ckpt", required=True)
    ap.add_argument("--noisy_dir", required=True)
    ap.add_argument("--clean_dir", required=True)
    ap.add_argument("--H", type=int, default=321)
    ap.add_argument("--W", type=int, default=481)

    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--eval_batch", type=int, default=0, help="0 => use --batch")
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--num_workers", type=int, default=4)
    ap.add_argument("--amp", action="store_true")

    ap.add_argument("--w_clean", type=float, default=0.5)
    ap.add_argument("--w_teacher", type=float, default=0.5)
    ap.add_argument("--w_res", type=float, default=0.0)

    ap.add_argument("--out_dir", default="runs_buifd_lite")
    ap.add_argument("--save_png", action="store_true")
    ap.add_argument("--debug_teacher", action="store_true")
    ap.add_argument("--no_bn", action="store_true", help="disable BN in student to be more NPU-friendly")

    args = ap.parse_args()
    if args.eval_batch == 0:
        args.eval_batch = None

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("[device]", device)
    ensure_dir(args.out_dir)

    exps = {
        #"A_dn56L16_ns64L5_f64": {"dn_features": 56, "dn_layers": 16, "ns_features": 64, "ns_layers": 5, "fuse_features": 64},
        #"B_dn56L18_ns56L4_f64": {"dn_features": 56, "dn_layers": 18, "ns_features": 56, "ns_layers": 4, "fuse_features": 64},
        #"C_dn64L16_ns64L4_f64": {"dn_features": 64, "dn_layers": 16, "ns_features": 64, "ns_layers": 4, "fuse_features": 64},
        #"D_dn56L18_ns56L5_f64": {"dn_features": 56, "dn_layers": 18, "ns_features": 56, "ns_layers": 5, "fuse_features": 64},
        "E_dn48L18_ns56L4_f64": {"dn_features": 48, "dn_layers": 18, "ns_features": 56, "ns_layers": 4, "fuse_features": 64},
    }

    for name, cfg in exps.items():
        run_exp(name, cfg, args, device)


if __name__ == "__main__":
    main()

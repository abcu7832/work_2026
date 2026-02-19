import torch
import torch.nn as nn

# 🔴 반드시 학습에 사용한 것과 동일한 정의를 import / 복붙
from lenet5_baseline import LeNet5Paper   # 파일명 맞게 수정

def export_onnx(
    pth_path: str,
    onnx_path: str = "lenet5_paper.onnx",
    opset: int = 11,
):
    device = torch.device("cpu")  # ONNX export는 CPU 권장

    # 1️⃣ 모델 생성 (구조 동일)
    model = LeNet5Paper(num_classes=10).to(device)

    # 2️⃣ 가중치 로드
    state = torch.load(pth_path, map_location=device)
    model.load_state_dict(state, strict=True)
    model.eval()

    # 3️⃣ 더미 입력
    # ⚠️ MNIST + Pad(2) → 32x32
    dummy = torch.randn(1, 1, 32, 32, device=device)

    # 4️⃣ ONNX export
    torch.onnx.export(
        model,
        dummy,
        onnx_path,
        input_names=["input"],
        output_names=["logits"],   # GaussianRBF 출력 (softmax 아님)
        opset_version=opset,
        do_constant_folding=True,
        dynamic_axes={
            "input": {0: "batch"},
            "logits": {0: "batch"},
        },
    )

    print(f"✅ ONNX saved: {onnx_path}")


if __name__ == "__main__":
    export_onnx(
        pth_path="lenet5_paper_exact.pth",  # ← 네 파일명
        onnx_path="lenet5_paper_exact.onnx",
        opset=11,
    )

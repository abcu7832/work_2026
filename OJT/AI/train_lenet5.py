import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms
from torch.utils.data import DataLoader

# -----------------------------
# LeNet5 (MNIST: 1x28x28)
# -----------------------------
class LeNet5(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 6, 5), nn.ReLU(), nn.AvgPool2d(2, 2),
            nn.Conv2d(6,16,5), nn.ReLU(), nn.AvgPool2d(2, 2),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(16*4*4, 120), nn.ReLU(),
            nn.Linear(120, 84), nn.ReLU(),
            nn.Linear(84, 10),
        )

    def forward(self, x):
        x = self.features(x)
        x = self.classifier(x)
        return x

def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("device:", device)

    # MNIST 기본 전처리: ToTensor()만 (0~1 스케일)
    tf = transforms.Compose([transforms.ToTensor()])

    train_ds = datasets.MNIST("./data", train=True, download=True, transform=tf)
    test_ds  = datasets.MNIST("./data", train=False, download=True, transform=tf)

    train_loader = DataLoader(train_ds, batch_size=128, shuffle=True, num_workers=2)
    test_loader  = DataLoader(test_ds, batch_size=256, shuffle=False, num_workers=2)

    model = LeNet5().to(device)
    opt = optim.Adam(model.parameters(), lr=2e-3, weight_decay=0.0) # lr = 0.002
    crit = nn.CrossEntropyLoss()

    best_acc = 0.0
    epochs = 10

    for ep in range(1, epochs+1):
        model.train()
        running = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            opt.zero_grad()
            out = model(x)
            loss = crit(out, y)
            loss.backward()
            opt.step()
            running += loss.item()

        # eval
        model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for x, y in test_loader:
                x, y = x.to(device), y.to(device)
                pred = model(x).argmax(dim=1)
                correct += (pred == y).sum().item()
                total += y.numel()

        acc = correct / total
        print(f"epoch {ep}/{epochs}  loss={running/len(train_loader):.4f}  acc={acc:.4f}")

        if acc > best_acc:
            best_acc = acc
            torch.save(model.state_dict(), "lenet5_best.pth")

    print("best_acc:", best_acc)
    print("saved: lenet5_best.pth")

if __name__ == "__main__":
    main()

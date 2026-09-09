# CDC(Clock Domain Crossing) 문제 완전 정리

CDC는 SoC 설계에서 가장 까다롭고 버그가 은밀하게 숨어있는 영역 중 하나입니다.

---

## 1. CDC란 무엇인가

**CDC(Clock Domain Crossing)**는 서로 다른 클럭 도메인(비동기 관계에 있는 클럭들) 사이에서 신호가 전달될 때 발생하는 모든 문제를 총칭합니다.

두 클럭이 서로 다른 소스에서 나오거나, 위상/주파수 관계가 고정되어 있지 않으면(비동기, asynchronous) 그 경계를 넘는 신호는 **셋업/홀드 타임 위반 위험**을 항상 안고 있습니다.

---

## 2. 근본 원인: Metastability (준안정 상태)

### 2.1 발생 메커니즘

- 플립플롭은 클럭 엣지 근처의 **setup/hold window** 안에서 데이터가 변하면, 출력이 0도 1도 아닌 중간 전압에 머무르다가 **예측 불가능한 시간 후에** 임의의 값(0 또는 1)으로 정착(resolve)합니다.
- 이 상태를 metastability라고 하며, 정착 시간이 확률적으로 분포하기 때문에 "얼마나 기다려야 안전한지"는 확률의 문제입니다.

### 2.2 MTBF (Mean Time Between Failures)

metastability로 인한 실패까지의 평균 시간을 계산하는 공식:

```
MTBF = e^(t_r / τ) / (T0 × f_clk × f_data)
```

- `t_r`: resolution time (동기화를 위해 준 여유 시간, 예: 1클럭 주기)
- `τ`: 플립플롭 공정 특성 상수 (기술 라이브러리마다 다름)
- `T0`: 플립플롭 고유 상수
- `f_clk`, `f_data`: 각각 수신 클럭 주파수, 데이터 변화 빈도

> **핵심 포인트**: metastability를 "완전히 없앨" 수는 없고, **동기화 스테이지를 늘려 실패 확률을 실용적으로 무시할 수준까지 낮추는 것**이 CDC 대응의 본질입니다.

---

## 3. CDC 문제의 유형별 분류

### 3.1 Single-bit CDC
한 비트 신호가 도메인을 건널 때 — 가장 단순하지만 기본이 되는 케이스.

### 3.2 Multi-bit CDC (버스 신호)
- 여러 비트가 동시에 넘어갈 때, 각 비트가 **서로 다른 시점에 resolve**될 수 있어 문제가 심각해집니다.
- 예: 4비트 값이 `0111` → `1000`으로 바뀌는 순간 넘어가면, 수신측에서 각 비트가 제각각 resolve되어 `0000`, `1111`, `0101` 등 **전혀 엉뚱한 값(코히런시 손실)**이 관측될 수 있습니다.

### 3.3 Pulse CDC
- 빠른 클럭 → 느린 클럭으로 넘어가는 **짧은 펄스**는 수신 클럭이 그 펄스를 아예 "못 보고 지나칠(pulse swallowing)" 위험이 있습니다.

### 3.4 Reconvergence (재수렴) CDC
- 하나의 소스 신호가 **두 개 이상의 서로 다른 동기화 경로**를 거쳐 다시 같은 로직에서 만날 때, 두 경로의 지연이 달라 **일시적으로 불일치하는 조합 로직 출력**(glitch, 잘못된 상태)이 생길 수 있습니다.
- CDC 버그 중 가장 찾기 어려운 유형입니다.

---

## 4. 해결 기법 (Synchronizer 종류)

### 4.1 2-Flop Synchronizer (가장 기본)

```
D → [FF1] → [FF2] → Q (동기화된 도메인 클럭 사용)
```

- FF1에서 metastability가 발생해도, FF2에서 resolve될 시간을 벌어줌.
- **단, single-bit 신호에만 사용 가능** (multi-bit에는 부적합).

### 4.2 3-Flop (또는 그 이상) Synchronizer

매우 높은 클럭 속도나 초고신뢰성이 요구되는 경우(항공우주, 자동차) FF를 하나 더 추가해 MTBF를 지수적으로 늘림.

### 4.3 Multi-bit 신호 처리법

**① Gray Code 인코딩**
- 인접한 값끼리 **딱 1비트만 차이**나도록 인코딩(예: FIFO의 read/write pointer).
- 여러 비트가 동시에 바뀌지 않으므로, 설령 동기화 중 값이 잘못 읽혀도 인접값(±1) 오차 정도로 제한됨.
- 카운터류(포인터) CDC에 표준적으로 사용.

**② Handshake (요청-확인) 방식**

```
송신 도메인: req 신호 발생 →
수신 도메인: req를 2FF로 동기화 → 처리 후 ack 발생 →
송신 도메인: ack를 2FF로 동기화 → 다음 데이터 전송
```

- 데이터 자체는 req가 안정된 이후에만 캡처하도록 보장 → multi-bit 데이터도 안전하게 전달.
- 단점: 처리량(throughput)이 느림 (round-trip 대기 필요).

**③ MUX 기반 동기화 (Enable 동기화)**
- 데이터 버스는 고정해두고, "이 데이터를 캡처해도 좋다"는 **enable 신호만 2FF로 동기화**.
- 데이터가 enable이 안정되기 전에 바뀌지 않는다는 설계적 보장이 전제 조건.

**④ Asynchronous FIFO**
- 실무에서 가장 널리 쓰이는 방식. 서로 다른 클럭의 write/read 포인터를 Gray code로 만들고, 각각 상대 도메인으로 2FF 동기화하여 full/empty 판단.
- 버스트 데이터 전송, 고속 스트리밍(카메라, MIPI 등)에 필수적으로 사용됨.

### 4.5 Pulse 동기화

- **Pulse stretcher / toggle synchronizer**: 짧은 펄스를 수신 클럭이 인식 가능한 폭으로 늘리거나, toggle FF로 변환 후 동기화하고 다시 edge-detect로 펄스화.

---

## 5. 설계 시 주의사항 (안전한 CDC 설계 원칙)

1. **동기화기는 클럭 도메인 경계에서 단 한 번만** 통과시키고, 이후 로직은 이미 동기화된 신호만 사용해야 함.
2. **동기화기 이후 신호에 조합 로직을 바로 걸지 않기** — 로직 안에서 skew가 생겨 reconvergence 문제를 유발.
3. **하나의 FF 출력을 여러 동기화기로 팬아웃하지 않기** (Non-common enable, 각기 다른 resolve 타이밍으로 인한 재수렴 위험).
4. Synchronizer FF는 **가능한 물리적으로 인접 배치** (backend에서 metastability-hardened cell 사용 권장).
5. Reset도 비동기 문제 대상: **Asynchronous assert, Synchronous de-assert** 원칙 적용 (reset synchronizer).

---

## 6. 검증(Verification) 방법론

CDC는 기능 시뮬레이션만으로는 절대 잡히지 않는 버그입니다 (시뮬레이터는 이상적인 타이밍으로 동작하기 때문). 그래서 전용 검증 단계가 필요합니다.

### 6.1 CDC Lint / Structural Check (정적 분석)

- 툴: Cadence JasperGold CDC, Synopsys SpyGlass CDC, Siemens Questa CDC
- 체크 항목:
  - 동기화되지 않은 크로싱 존재 여부
  - Multi-bit 신호가 2FF만으로 부적절하게 처리된 경우
  - Reconvergence 경로 탐지
  - Gray code 위반, 미완성 handshake 등

### 6.2 Formal Verification

Reconvergence 등 복잡한 케이스는 정적 룰만으로 잡기 어려워 **formal proof**로 논리적으로 안전성을 증명.

### 6.3 Metastability Injection Simulation

시뮬레이션에서 CDC 경로에 **인위적으로 랜덤 지연/글리치를 주입**해 다운스트림 로직이 여전히 정상 동작하는지 확인 (예: X-propagation 방식).

### 6.4 Gate-level Timing 검증

False path 지정(synchronizer 앞단은 STA에서 timing 분석 대상이 아니므로 `set_false_path`로 명시) — 이게 누락되면 STA 툴이 비동기 경로에 대해 무의미하게 타이밍을 맞추려다 실패하거나 잘못된 최적화를 함.

---

## 7. 관련 개념 정리표

| 개념 | 설명 |
|---|---|
| Metastability | FF 출력이 중간전압에서 임의 시간 머무는 현상 |
| MTBF | 동기화 실패까지의 평균 시간, 스테이지 늘릴수록 지수적으로 증가 |
| Reconvergence | 한 신호가 여러 경로로 동기화된 후 다시 만나 생기는 불일치 |
| Gray Code | 인접값 간 1비트만 바뀌는 인코딩, 포인터 CDC에 사용 |
| Async FIFO | 이종 클럭 간 버퍼링 + 안전한 포인터 비교 구조 |
| False Path | STA에서 CDC 경로를 타이밍 분석 대상에서 제외하는 제약 |

---

## 요약

CDC 문제의 본질은 "정착 시간이 불확실한 신호를 안전하게 인접 도메인으로 넘기는 것"이며, 해법은 크게:

1. **신호 성격에 맞는 동기화 구조 선택** (2FF, handshake, gray code, async FIFO)
2. **재수렴/멀티비트 코히런시 문제 회피**
3. **정적 분석 + formal + 시뮬레이션의 다층 검증**

으로 요약됩니다.

---

## 8. Q&A 딥다이브

### 8.1 Handshake 방식에서 req/ack는 Multi-bit이 아니다

Multi-bit CDC 처리법 중 **Handshake 방식**을 설명할 때 등장하는 `req`/`ack` 신호는 **single-bit**입니다. multi-bit인 것은 함께 전달되는 **data 신호**이고, req/ack는 그 data를 "언제 안전하게 읽어도 되는지" 알려주는 제어 신호 역할만 합니다.

| 신호 | 비트 수 | 역할 |
|---|---|---|
| `req` (request) | 1비트 | "데이터 보낼 준비 됐다"는 신호 |
| `ack` (acknowledge) | 1비트 | "데이터 잘 받았다"는 신호 |
| `data` | **multi-bit** | 실제로 전달하려는 값 |

**핵심 아이디어**: data 자체는 절대 도메인을 건너면서 직접 동기화하지 않는다. 대신 data가 안정적으로 유지되는 "타이밍 창"을 req/ack라는 single-bit 신호로 만들어주고, 그 창 안에서만 data를 읽는다.

#### 4-phase Handshake 전체 시퀀스

```
1. [Tx 도메인] data 세팅 → 충분히 안정화된 후 req = 1
2. [Tx→Rx CDC] req를 2FF synchronizer로 Rx 도메인에 전달
3. [Rx 도메인] 동기화된 req_sync = 1 감지 → data 캡처 → ack = 1
4. [Rx→Tx CDC] ack를 2FF synchronizer로 Tx 도메인에 전달
5. [Tx 도메인] 동기화된 ack_sync = 1 감지 → req = 0으로 내림 (다음 전송 준비)
6. [Tx→Rx CDC] req = 0을 다시 동기화 → Rx도 ack = 0으로 내림 (원상복귀)
7. [Rx→Tx CDC] ack = 0을 동기화 → Tx가 이걸 확인하고 나서야 진짜로 "다음 데이터 전송" 가능
```

5~7번 단계(req/ack를 다시 0으로 내리는 과정)까지 포함해야 완전한 **4-phase**이고, 이 과정을 생략하고 req/ack를 toggle 방식(0→1→0 대신 매번 반전)으로 처리하는 걸 **2-phase handshake**라고 한다. 2-phase는 latency가 짧지만 회로가 조금 더 복잡하다.

> req 동기화 완료 = data가 안정적이라는 보장 → 그때 캡처 → ack로 확인 회신 → 그 확인이 돌아와야 다음 데이터로 넘어감.

---

### 8.2 "Glitch"의 두 가지 서로 다른 의미

FF를 여러 번 거치는 상황에서 "글리치가 생긴 데이터"라고 할 때, 이는 사실 **완전히 다른 두 가지 현상**을 가리킬 수 있어 구분이 필요하다.

| 구분 | 조합 로직 Glitch | FF 자체의 Metastability |
|---|---|---|
| 원인 | 배선 지연 차이로 조합로직 출력이 잠깐 튐 | FF가 setup/hold 위반으로 중간전압에 머무름 |
| Glitch가 나는 곳 | FF **앞단**(조합로직), FF는 그 값을 정상 캡처 | **FF 자신의 출력**이 흔들림 |
| FF가 캡처하는 값 | 명확한 0 또는 1 (그냥 "틀린" 값) | 중간 전압 (애매한 값) |
| FF를 더 붙이면? | **소용없음** — 틀린 값을 정확히 전달할 뿐 | **도움 됨** — 진동이 가라앉을 시간을 벌어줌 |
| 근본 해결책 | 신호 소스를 아예 **레지스터(FF) 출력**으로 만들어야 함 | Synchronizer stage 추가 (2FF, 3FF...) |

#### (A) 조합 로직 Glitch — FF 앞단에서 발생

```
        ┌─────┐
sig_a ──┤     │
        │ AND ├──── glitchy_signal ──→ [FF1] → [FF2] → Q
sig_b ──┤     │      (동기화기 입력)
        └─────┘
```

`sig_a`, `sig_b`가 같은 클럭 도메인 안에서 만들어져도 게이트를 통과하는 배선 지연이 서로 다르면, AND 결과가 최종값에 도달하기 전 짧은 순간 여러 번 튈 수 있다.

```
glitchy_signal:  0 ─┐ ┌─┐   ┌────── 1 (최종적으로 안정)
                     └─┘ └───
```

이때 FF1의 클럭 엣지가 하필 이 glitch 구간과 겹치면, FF1은 **glitch 중 우연히 걸린 값을 그대로, 정상적으로** 캡처해버린다. 이는 setup/hold 위반이 아니고 metastable도 아니다. 그냥 "그 순간 존재했던, 하지만 의도치 않은 확정값"을 캡처한 것뿐이다. 따라서 FF2, FF3을 아무리 더 붙여도 **틀린 값을 정확하게 전달**할 뿐 고쳐지지 않는다.

**해결책**: 동기화기에 넣는 신호는 반드시 레지스터(FF)의 Q 출력이어야 한다.

```
❌ sig_a, sig_b (조합 로직 출력) → AND → 동기화기 입력
✅ sig_a, sig_b → AND → [FF_local] → 동기화기 입력
```

#### (B) FF1 자체가 Metastable해지는 경우 — FF 출력 자체가 흔들림

```
D 신호 (다른 클럭 도메인에서 옴) ──→ [FF1] ──→ [FF2] ──→ Q
                                    ↑clk1        ↑clk2
```

`D`가 clk1 엣지 바로 근처의 좁은 setup/hold window 안에서 바뀌면, FF1 내부 latch가 "0을 잡을지 1을 잡을지" 결정을 못 내리고 중간 전압에서 진동하다 어느 시점에 정착한다.

```
FF1의 Q 출력 전압:
VDD ─────────────────────────────────
                    ╱‾╲  ╱╲    ╱‾‾‾‾‾  ← 결국 여기서 1로 정착(resolve)
                   ╱   ╲╱  ╲  ╱
    ─ ─ ─ ─ ─ ─ ─ ─      ╲╱─      ─ ─ ─
GND ─────────────────────────────────
     ↑clk1 엣지
```

이 파형이 FF2에 도달했을 때 두 가지로 갈린다.

- **경우 1 (대부분)**: FF2의 클럭 엣지가 올 때쯤엔 이미 FF1이 정착 완료 → FF2는 정상적으로 확정값을 캡처.
- **경우 2 (매우 드묾)**: FF2의 클럭 엣지가 왔는데도 FF1이 아직 안 가라앉음 → FF2 자신도 setup time 위반과 같은 상황에 놓여 metastable해질 수 있음 (한 단계 더 전파).

Q(FF2 출력)는 결국 언젠가는 반드시 0이나 1 중 하나로 확실히 정착한다. 문제는 (1) 얼마나 걸릴지 예측 불가, (2) 최종적으로 어느 값이 될지 예측 불가, (3) 다음 단이 아직 흔들리는 도중 값을 읽으면 문제가 한 단 더 전파된다는 점이다.

**해결책**: 2FF(혹은 3FF, 4FF) synchronizer로 "흔들림이 가라앉을 시간(1클럭 주기 이상)"을 벌어준다 — 이것이 바로 synchronizer가 존재하는 근본 이유다.

---

### 8.3 CDC 검증은 기존 설계 흐름과 "병행하는" 별도 트랙

일반적인 디지털 설계 흐름은 다음과 같다.

```
RTL → RTL SIM → SYNTHESIS → STA → GATESIM → LAYOUT
```

이 흐름은 **"기능이 맞는가" + "일반적인 intra-domain 타이밍이 맞는가"**를 검증하는 것이 목적이며, CDC 문제는 이 흐름의 어느 단계도 원래 목적상 커버하지 못한다.

| 기존 단계 | 원래 목적 | CDC를 못 잡는 이유 |
|---|---|---|
| RTL SIM | 기능 검증 | 이상적 타이밍이라 metastability 자체가 존재 안 함 |
| SYNTHESIS | 논리 → 게이트 변환 | 구조 변환일 뿐, CDC 안전성과 무관 |
| STA | intra-domain 타이밍 검증 | 비동기 클럭 쌍은 애초에 분석 대상이 아님 (false_path로 빼야 함) |
| GATE SIM | 게이트 레벨 기능 재검증 | RTL SIM과 마찬가지로 이상적 타이밍 |
| LAYOUT | 물리적 배치/배선 | 배선 지연은 반영되지만 CDC 구조를 새로 만들지는 않음 |

따라서 CDC 전용 검증(Lint, Formal, Metastability injection)은 기존 흐름 **사이사이에 병행해서(parallel) 끼워지는 별도 트랙**이다.

```
RTL
 │
 ├─▶ [CDC Lint] 구조 분석으로 크로싱 지점 탐지, waiver 처리
 ├─▶ [Formal CDC] Reconvergence 등 애매한 케이스 논리적 증명
 ▼
RTL SIM
 ├─▶ [Metastability Injection Sim] X-propagation으로 다운스트림 견고성 확인
 ▼
SYNTHESIS  (ASYNC_REG / dont_touch 등 synchronizer 속성 반영)
 ▼
STA
 ├─▶ [set_false_path / set_max_delay 적용 여부 sign-off]
 ▼
GATE SIM
 ▼
LAYOUT
 └─▶ [Post-layout STA에서 max_delay·FF 인접배치 재확인]
```

**한 줄 요약**: 기존 흐름은 "기능·일반 타이밍"을 검증하고, CDC 흐름은 그 위에 "비동기 경계를 안전하게 넘고 있는가"를 검증하는 평행한 검증 트랙이다.

---

## 9. 결론: CDC 해결을 위한 RTL 설계 원칙

> **"신호의 성격을 파악하고, 그 성격에 맞는 표준 동기화 패턴을 처음부터 적용하며, 이후 툴로 빠짐없이 검증한다."**

### 9.1 설계 전: 클럭 도메인부터 명확히 나누기

RTL을 짜기 전에 클럭 도메인 다이어그램을 먼저 그리고, 어느 신호가 어느 도메인 경계를 넘는지 **설계 초기에 미리 목록화**한다. 이 목록 없이 코딩부터 들어가면, 나중에 CDC lint 결과 수십~수백 개의 크로싱이 쏟아져 나와도 어느 게 진짜 문제인지 구분하기 힘들어진다.

### 9.2 신호 종류별 표준 패턴 (가장 중요한 원칙)

"이 신호가 어떤 카테고리에 속하는가"만 정확히 분류하면 해법은 이미 정해져 있다.

| 신호 종류 | 사용할 패턴 | 절대 하지 말 것 |
|---|---|---|
| Single-bit 레벨 신호 (enable, mode) | 2FF (고신뢰 요구시 3FF) synchronizer | FF 하나만 쓰고 넘어가기 |
| Single-bit 펄스 신호 | Toggle + 수신측 edge detect, pulse stretcher | 원본 펄스를 그냥 2FF에 통과 (사라질 위험) |
| Multi-bit 데이터 (한 번 전송) | req/ack 4-phase handshake, MUX+enable 동기화 | data를 2FF에 그냥 통과 |
| Multi-bit 카운터/포인터 (FIFO) | Gray code 변환 후 2FF | Binary 그대로 2FF에 통과 |
| 연속 스트리밍 데이터 | Asynchronous FIFO | 매 데이터마다 handshake (너무 느림) |
| Reset 신호 | Async assert / Sync de-assert | 비동기 reset을 여러 도메인에 직결 |

### 9.3 RTL 코딩 규칙

**① Synchronizer FF는 목적지 클럭 기준으로만 작성**
```verilog
always @(posedge clk_dst or negedge rst_n) begin  // 반드시 수신 도메인 클럭
    if (!rst_n) begin meta_ff <= 0; sync_ff <= 0; end
    else begin
        meta_ff <= async_in;
        sync_ff <= meta_ff;
    end
end
```

**② FF1과 FF2 사이 조합 로직 절대 금지**
```verilog
sync_ff <= meta_ff;         // ✅
sync_ff <= meta_ff & en;    // ❌ 절대 금지
```

**③ 하나의 FF 출력을 여러 synchronizer로 팬아웃 금지**
```verilog
// ❌ 위험: 같은 소스가 두 개의 서로 다른 synchronizer로 나뉨 (reconvergence 위험)
sync_a <= meta_a; meta_a <= src;
sync_b <= meta_b; meta_b <= src;
```
꼭 나눠야 한다면 **동기화된 이후(sync_ff 출력)**에서 나누는 게 원칙이다. metastable할 수 있는 지점을 두 갈래로 복제하면 안 된다.

**④ Synthesis 최적화 방지 속성 명시**
```verilog
(* ASYNC_REG = "TRUE" *) reg meta_ff, sync_ff;  // Xilinx 예시
```
Synopsys 계열은 `set_dont_touch`, `set_ungroup false` 등을 SDC/TCL에서 지정.

**⑤ 소스 신호는 반드시 레지스터 출력이어야 함**
```verilog
// ❌ 조합 로직 출력을 바로 동기화기에 넣지 않기
wire glitchy = a & b;
sync_ff <= glitchy;  // 위험

// ✅ 로컬 FF로 한 번 정리한 뒤 동기화
reg reg_ab;
always @(posedge clk_src) reg_ab <= a & b;
sync_ff <= reg_ab;  // 안전
```

### 9.4 검증 단계 (설계 완료 후 통과시킬 게이트)

```
RTL 완성
   ↓
① CDC Lint 통과 (waiver는 반드시 근거와 함께)
   ↓
② Formal CDC로 reconvergence 등 애매한 케이스 증명
   ↓
③ RTL SIM에서 metastability injection으로 다운스트림 견고성 확인
   ↓
④ STA에서 set_false_path / set_max_delay가 CDC 경로에 정확히, 빠짐없이 적용됐는지 sign-off
   ↓
⑤ Post-layout STA에서 max_delay 제약이 실제 배선 후에도 만족되는지 재확인
```

### 9.5 최종 결론

> **신호를 성격별로 분류해 이미 검증된 표준 synchronizer 패턴만 사용하고, FF 사이 조합로직·팬아웃·소스 glitch를 코딩 룰로 원천 차단한 뒤, CDC lint + formal + injection sim + false_path STA로 4중 검증한다.**

CDC는 사후에 "고치는" 게 아니라, 설계 시점에 미리 원칙을 지키는 것(prevention)이 8할이고, 나머지 2할이 툴로 확인하는 것(verification)인 영역이다.
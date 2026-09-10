# RTL 설계 완전 정리

RTL 설계에서 고려해야 할 영역은 광범위하다. 그 중에서도 **CDC(Clock Domain Crossing)**는 비동기 경계에서 발생하는 특수하고 까다로운 문제 영역으로, 기능 시뮬레이션만으로는 버그를 잡을 수 없어 별도의 검증 트랙이 필요하다. 이 문서는 CDC를 RTL 설계 맥락 안에서 다루되, 그 깊이를 충분히 유지한다.

---

## 목차

1. [CDC (Clock Domain Crossing)](#1-cdc-clock-domain-crossing)
2. [Reset 전략](#2-reset-전략)
3. [FSM(상태 머신) 설계](#3-fsm상태-머신-설계)
4. [Synthesis-friendly 코딩](#4-synthesis-friendly-코딩-합성-결과를-예측-가능하게)
5. [Timing Closure](#5-timing-closure-setuphold-일반-타이밍)
6. [Low Power 설계](#6-low-power-설계)
7. [Arbitration & Multi-master 설계](#7-arbitration--multi-master-설계)
8. [메모리(SRAM/Register File) 설계 고려사항](#8-메모리sramregister-file-설계-고려사항)
9. [DFT (Design for Test) 고려사항](#9-dft-design-for-test-고려사항)
10. [코드 품질 / 검증 관점](#10-코드-품질--검증-관점)
11. [재사용성 / 유지보수 관점](#11-재사용성--유지보수-관점)
12. [Q&A 딥다이브](#12-qa-딥다이브)

---

## 1. CDC (Clock Domain Crossing)

CDC는 SoC 설계에서 가장 까다롭고 버그가 은밀하게 숨어있는 영역 중 하나다. RTL 설계 전체 맥락에서 볼 때, CDC는 "비동기 경계"에서 발생하는 특정 문제를 다루는 전문 영역이며, 기능 시뮬레이션만으로는 절대 잡히지 않기 때문에 별도의 정적 분석 + formal + 시뮬레이션 검증 트랙이 병행되어야 한다.

### 1.1 CDC란 무엇인가

**CDC(Clock Domain Crossing)**는 서로 다른 클럭 도메인(비동기 관계에 있는 클럭들) 사이에서 신호가 전달될 때 발생하는 모든 문제를 총칭한다.

두 클럭이 서로 다른 소스에서 나오거나, 위상/주파수 관계가 고정되어 있지 않으면(비동기, asynchronous) 그 경계를 넘는 신호는 **셋업/홀드 타임 위반 위험**을 항상 안고 있다.

### 1.2 근본 원인: Metastability (준안정 상태)

#### 발생 메커니즘

- 플립플롭은 클럭 엣지 근처의 **setup/hold window** 안에서 데이터가 변하면, 출력이 0도 1도 아닌 중간 전압에 머무르다가 **예측 불가능한 시간 후에** 임의의 값(0 또는 1)으로 정착(resolve)한다.
- 이 상태를 metastability라고 하며, 정착 시간이 확률적으로 분포하기 때문에 "얼마나 기다려야 안전한지"는 확률의 문제다.

#### MTBF (Mean Time Between Failures)

metastability로 인한 실패까지의 평균 시간을 계산하는 공식:

```
MTBF = e^(t_r / τ) / (T0 × f_clk × f_data)
```

- `t_r`: resolution time (동기화를 위해 준 여유 시간, 예: 1클럭 주기)
- `τ`: 플립플롭 공정 특성 상수 (기술 라이브러리마다 다름)
- `T0`: 플립플롭 고유 상수
- `f_clk`, `f_data`: 각각 수신 클럭 주파수, 데이터 변화 빈도

> **핵심 포인트**: metastability를 "완전히 없앨" 수는 없고, **동기화 스테이지를 늘려 실패 확률을 실용적으로 무시할 수준까지 낮추는 것**이 CDC 대응의 본질이다.

### 1.3 CDC 문제의 유형별 분류

#### Single-bit CDC
한 비트 신호가 도메인을 건널 때 — 가장 단순하지만 기본이 되는 케이스.

#### Multi-bit CDC (버스 신호)
- 여러 비트가 동시에 넘어갈 때, 각 비트가 **서로 다른 시점에 resolve**될 수 있어 문제가 심각해진다.
- 예: 4비트 값이 `0111` → `1000`으로 바뀌는 순간 넘어가면, 수신측에서 각 비트가 제각각 resolve되어 `0000`, `1111`, `0101` 등 **전혀 엉뚱한 값(코히런시 손실)**이 관측될 수 있다.

#### Pulse CDC
- 빠른 클럭 → 느린 클럭으로 넘어가는 **짧은 펄스**는 수신 클럭이 그 펄스를 아예 "못 보고 지나칠(pulse swallowing)" 위험이 있다.

#### Reconvergence (재수렴) CDC
- 하나의 소스 신호가 **두 개 이상의 서로 다른 동기화 경로**를 거쳐 다시 같은 로직에서 만날 때, 두 경로의 지연이 달라 **일시적으로 불일치하는 조합 로직 출력**(glitch, 잘못된 상태)이 생길 수 있다.
- CDC 버그 중 가장 찾기 어려운 유형이다.

### 1.4 해결 기법 (Synchronizer 종류)

#### 2-Flop Synchronizer (가장 기본)

```
D → [FF1] → [FF2] → Q (동기화된 도메인 클럭 사용)
```

- FF1에서 metastability가 발생해도, FF2에서 resolve될 시간을 벌어줌.
- **단, single-bit 신호에만 사용 가능** (multi-bit에는 부적합).

#### 3-Flop (또는 그 이상) Synchronizer

매우 높은 클럭 속도나 초고신뢰성이 요구되는 경우(항공우주, 자동차) FF를 하나 더 추가해 MTBF를 지수적으로 늘린다.

#### Multi-bit 신호 처리법

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

#### Pulse 동기화

- **Pulse stretcher / toggle synchronizer**: 짧은 펄스를 수신 클럭이 인식 가능한 폭으로 늘리거나, toggle FF로 변환 후 동기화하고 다시 edge-detect로 펄스화.

### 1.5 설계 시 주의사항 (안전한 CDC 설계 원칙)

1. **동기화기는 클럭 도메인 경계에서 단 한 번만** 통과시키고, 이후 로직은 이미 동기화된 신호만 사용해야 함.
2. **동기화기 이후 신호에 조합 로직을 바로 걸지 않기** — 로직 안에서 skew가 생겨 reconvergence 문제를 유발.
3. **하나의 FF 출력을 여러 동기화기로 팬아웃하지 않기** (Non-common enable, 각기 다른 resolve 타이밍으로 인한 재수렴 위험).
4. Synchronizer FF는 **가능한 물리적으로 인접 배치** (backend에서 metastability-hardened cell 사용 권장).
5. Reset도 비동기 문제 대상: **Asynchronous assert, Synchronous de-assert** 원칙 적용 (reset synchronizer).

#### RTL 코딩 규칙

**① Synchronizer FF는 목적지 클럭 기준으로만 작성**
```verilog
always @(posedge clk_dst or negedge rst_n) begin
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

**③ Synthesis 최적화 방지 속성 명시**
```verilog
(* ASYNC_REG = "TRUE" *) reg meta_ff, sync_ff;  // Xilinx 예시
```

### 1.6 신호 종류별 표준 패턴

| 신호 종류 | 사용할 패턴 | 절대 하지 말 것 |
|---|---|---|
| Single-bit 레벨 신호 (enable, mode) | 2FF (고신뢰 요구시 3FF) synchronizer | FF 하나만 쓰고 넘어가기 |
| Single-bit 펄스 신호 | Toggle + 수신측 edge detect, pulse stretcher | 원본 펄스를 그냥 2FF에 통과 (사라질 위험) |
| Multi-bit 데이터 (한 번 전송) | req/ack 4-phase handshake, MUX+enable 동기화 | data를 2FF에 그냥 통과 |
| Multi-bit 카운터/포인터 (FIFO) | Gray code 변환 후 2FF | Binary 그대로 2FF에 통과 |
| 연속 스트리밍 데이터 | Asynchronous FIFO | 매 데이터마다 handshake (너무 느림) |
| Reset 신호 | Async assert / Sync de-assert | 비동기 reset을 여러 도메인에 직결 |

### 1.7 관련 개념 정리표

| 개념 | 설명 |
|---|---|
| Metastability | FF 출력이 중간전압에서 임의 시간 머무는 현상 |
| MTBF | 동기화 실패까지의 평균 시간, 스테이지 늘릴수록 지수적으로 증가 |
| Reconvergence | 한 신호가 여러 경로로 동기화된 후 다시 만나 생기는 불일치 |
| Gray Code | 인접값 간 1비트만 바뀌는 인코딩, 포인터 CDC에 사용 |
| Async FIFO | 이종 클럭 간 버퍼링 + 안전한 포인터 비교 구조 |
| False Path | STA에서 CDC 경로를 타이밍 분석 대상에서 제외하는 제약 |

### 1.8 검증(Verification) 방법론

CDC는 기능 시뮬레이션만으로는 절대 잡히지 않는 버그다 (시뮬레이터는 이상적인 타이밍으로 동작하기 때문). 그래서 아래와 같이 기존 설계 흐름과 **병행하는 별도 트랙**이 필요하다.

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

#### CDC Lint / Structural Check (정적 분석)

- 툴: Cadence JasperGold CDC, Synopsys SpyGlass CDC, Siemens Questa CDC
- 체크 항목:
  - 동기화되지 않은 크로싱 존재 여부
  - Multi-bit 신호가 2FF만으로 부적절하게 처리된 경우
  - Reconvergence 경로 탐지
  - Gray code 위반, 미완성 handshake 등

#### Formal Verification

Reconvergence 등 복잡한 케이스는 정적 룰만으로 잡기 어려워 **formal proof**로 논리적으로 안전성을 증명.

#### Metastability Injection Simulation

시뮬레이션에서 CDC 경로에 **인위적으로 랜덤 지연/글리치를 주입**해 다운스트림 로직이 여전히 정상 동작하는지 확인 (예: X-propagation 방식).

#### Gate-level Timing 검증

False path 지정(synchronizer 앞단은 STA에서 timing 분석 대상이 아니므로 `set_false_path`로 명시) — 이게 누락되면 STA 툴이 비동기 경로에 대해 무의미하게 타이밍을 맞추려다 실패하거나 잘못된 최적화를 한다.

---

## 2. Reset 전략

CDC 다음으로 실무에서 가장 많이 버그가 나는 영역.

- **Async assert / Sync de-assert**: reset을 걸 때는 즉시(비동기) 걸리게 하고, 풀 때는 클럭에 동기화해서 풀어야 함. 그냥 비동기 reset을 걸어놓기만 하면 reset이 풀리는 순간 setup/hold 위반이 날 수 있음.
- **Reset domain crossing**: reset 신호 자체도 클럭 도메인이 다르면 CDC처럼 동기화가 필요함.
- **Reset tree 부담**: 큰 SoC에서 global reset을 fan-out 많은 곳에 걸면 reset insertion delay가 커져 reset skew 문제가 생김.
- **Power-on reset vs soft reset 구분**: 어떤 레지스터가 POR에서만 초기화되고, 어떤 게 소프트 리셋에도 초기화돼야 하는지 명확히 설계해야 함.

---

## 3. FSM(상태 머신) 설계

- **State encoding 방식 선택**: binary vs one-hot vs gray.
  - one-hot: 디코딩 로직이 단순해지지만 FF 개수가 늘어남 (FPGA에서 선호)
  - binary: area 민감한 ASIC에서 선호
- **불법 상태(illegal state) 처리**: FSM이 정의되지 않은 상태에 빠졌을 때(예: SEU, 방사선 에러) 복구할 수 있는 default case를 반드시 넣어야 함.

```verilog
case(state)
    S0: ...
    S1: ...
    default: state <= S0;  // 안전장치, 빠뜨리면 latch 유추 위험
endcase
```

- **Output glitch**: Moore FSM(출력이 상태에만 의존)이 Mealy FSM(출력이 입력에도 의존)보다 조합 로직 glitch에 안전.

---

## 4. Synthesis-friendly 코딩 (합성 결과를 예측 가능하게)

- **Latch 의도치 않은 생성 방지**: `always @(*)` 블록에서 if/case의 모든 분기를 다 채우지 않으면 latch가 추론됨.

```verilog
// ❌ else 없음 → latch 생성
always @(*) if (en) out = in;

// ✅
always @(*) begin
    if (en) out = in;
    else    out = 0;
end
```

- **Blocking(`=`) vs Non-blocking(`<=`) 대입 규칙**: combinational 로직은 `=`, sequential(FF)은 `<=`을 일관되게 써야 함. 섞어 쓰면 시뮬레이션-합성 불일치(mismatch) 버그가 생김.
- **Full case / parallel case 관련 pragma 남용 주의**: 실제 하드웨어 동작과 시뮬레이션 동작이 달라지는 원인이 될 수 있음.

---

## 5. Timing Closure (Setup/Hold, 일반 타이밍)

- **Critical path 관리**: 조합 로직 depth가 너무 깊으면 파이프라인 스테이지를 추가해서 나눠야 함.
- **Hold time violation**: setup은 클럭을 느리게 하면 해결되지만, hold는 클럭 속도와 무관하게 항상 만족해야 함 — 특히 register-to-register 경로가 너무 짧을 때(0-지연 경로) 발생하기 쉬움.
- **Multicycle path**: 어떤 데이터는 원래 여러 클럭에 걸쳐 안정화되도록 설계되는 경우가 있는데, 이걸 STA에 `set_multicycle_path`로 명시하지 않으면 불필요하게 빡빡한 타이밍 요구가 생김.

---

## 6. Low Power 설계

- **Clock gating**: 안 쓰는 블록의 클럭을 꺼서 dynamic power 절감. 다만 clock gating cell 자체에 glitch가 있으면 안 되므로 표준 ICG(Integrated Clock Gating) cell을 써야 함.

```verilog
// 위험한 수동 clock gating (glitch 위험)
assign gated_clk = clk & enable;

// 안전: 표준 ICG cell 또는 latch 기반 클럭 게이팅 사용
```

- **Power domain (UPF/CPF)**: 여러 전압 도메인을 쓸 경우 level shifter, isolation cell, retention register가 domain 경계마다 필요.
- **Power domain crossing**은 CDC와 유사하게 별도의 정적 검증(UPF lint)이 필요.

---

## 7. Arbitration & Multi-master 설계

- 여러 마스터가 하나의 자원(버스, 메모리)에 동시 접근할 때 **공정성(fairness)**과 **starvation 방지**를 고려한 arbiter 설계 필요 (round-robin, priority-based 등).
- Handshake 프로토콜(예: AXI의 valid/ready)에서 **deadlock 가능성**을 반드시 검토해야 함 — 특히 ready가 valid에 종속되면 안 되는 등 프로토콜 규칙 준수.

---

## 8. 메모리(SRAM/Register File) 설계 고려사항

- **Read-before-write / write-before-read** 동작 정의를 명확히 하고 RTL 모델이 실제 memory compiler IP의 동작과 일치하는지 확인.
- **Memory BIST/redundancy**를 고려한 인터페이스 설계.
- **ECC(에러 정정)**가 필요한 메모리는 인코더/디코더 지연을 파이프라인에 반영.

---

## 9. DFT (Design for Test) 고려사항

- **Scan chain 삽입을 고려한 설계**: 모든 FF가 scan 가능한 형태(scan flop)로 설계 가능해야 함. 비동기 reset/set이 있는 FF는 scan 삽입이 더 까다로움.
- **Test mode에서의 clock/reset 처리**: 여러 클럭 도메인의 scan chain을 어떻게 묶을지(clock domain별로 나눌지) 미리 고려.
- Clock gating cell도 test mode에서는 bypass할 수 있게 설계해야 ATPG(자동 테스트 패턴 생성) 커버리지가 나옴.

---

## 10. 코드 품질 / 검증 관점

- **Lint (기능 lint, CDC lint와는 별개)**: 배열 범위 초과, 부호 없는/있는 비교 오류, 사용되지 않는 신호 등을 정적으로 검사 (Verilator, SpyGlass Lint 등).
- **Coverage (기능/코드 커버리지)**: 시뮬레이션이 RTL의 모든 분기, 모든 상태 전이를 실제로 exercise 했는지 확인.
- **X-propagation 인식 설계**: 시뮬레이션에서 X(unknown)가 실제 하드웨어에서는 특정 값(0 또는 1)으로 resolve되는데, RTL이 이 차이 때문에 시뮬레이션과 실제 동작이 달라지지 않도록 주의 (예: `case`문에서 X를 우연히 특정 분기로 매칭시키는 실수).

---

## 11. 재사용성 / 유지보수 관점

- **파라미터화(parameterization)**: 버스 폭, 깊이 등을 하드코딩하지 않고 `parameter`/`localparam`으로 관리해 재사용성 확보.
- **Naming convention 일관성**: 클럭(`clk_*`), reset(`rst_n_*`), active-low 신호(`*_n`) 등 팀 표준을 지켜야 리뷰/유지보수가 쉬움.
- **Assertion 내장(SVA)**: 설계자가 "이 신호는 이런 조건에서 절대 이렇게 안 된다"는 가정을 RTL에 assertion으로 박아두면, 버그를 시뮬레이션 단계에서 훨씬 빨리 잡을 수 있음.

---

## 요약 표

| 카테고리 | 핵심 이슈 |
|---|---|
| Reset | Async assert / Sync de-assert, reset domain crossing |
| **CDC** | **Metastability, 동기화 구조 선택, reconvergence, 전용 검증 트랙** |
| FSM | 불법 상태 복구, encoding 방식 |
| 코딩 스타일 | Latch 방지, blocking/non-blocking 일관성 |
| Timing | Critical path, hold violation, multicycle path |
| Low Power | Clock gating glitch 방지, power domain crossing |
| Arbitration | Fairness, deadlock 방지 |
| Memory | R/W 정책, ECC, BIST 연동 |
| DFT | Scan 가능한 FF 설계, test mode clock/reset |
| 검증 | Lint, coverage, X-propagation |
| 유지보수 | 파라미터화, naming, assertion |

---

## 12. Q&A 딥다이브

### 12.1 Handshake 방식에서 req/ack는 Multi-bit이 아니다

Multi-bit CDC 처리법 중 **Handshake 방식**을 설명할 때 등장하는 `req`/`ack` 신호는 **single-bit**다. multi-bit인 것은 함께 전달되는 **data 신호**이고, req/ack는 그 data를 "언제 안전하게 읽어도 되는지" 알려주는 제어 신호 역할만 한다.

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

### 12.2 "Glitch"의 두 가지 서로 다른 의미

FF를 여러 번 거치는 상황에서 "글리치가 생긴 데이터"라고 할 때, 이는 사실 **완전히 다른 두 가지 현상**을 가리킬 수 있어 구분이 필요하다.

| 구분 | 조합 로직 Glitch | FF 자체의 Metastability |
|---|---|---|
| 원인 | 배선 지연 차이로 조합로직 출력이 잠깐 튐 | FF가 setup/hold 위반으로 중간전압에 머무름 |
| Glitch가 나는 곳 | FF **앞단**(조합로직), FF는 그 값을 정상 캡처 | **FF 자신의 출력**이 흔들림 |
| FF가 캡처하는 값 | 명확한 0 또는 1 (그냥 "틀린" 값) | 중간 전압 (애매한 값) |
| FF를 더 붙이면? | **소용없음** — 틀린 값을 정확히 전달할 뿐 | **도움 됨** — 진동이 가라앉을 시간을 벌어줌 |
| 근본 해결책 | 신호 소스를 아예 **레지스터(FF) 출력**으로 만들어야 함 | Synchronizer stage 추가 (2FF, 3FF...) |

---

### 12.3 CDC 검증은 기존 설계 흐름과 "병행하는" 별도 트랙

```
RTL → RTL SIM → SYNTHESIS → STA → GATESIM → LAYOUT
```

이 흐름은 **"기능이 맞는가" + "일반적인 intra-domain 타이밍이 맞는가"**를 검증하는 것이 목적이며, CDC 문제는 이 흐름의 어느 단계도 원래 목적상 커버하지 못한다. CDC는 섹션 2.8에 정리된 별도 트랙으로 커버해야 한다.

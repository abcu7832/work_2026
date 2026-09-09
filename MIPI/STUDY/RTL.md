# RTL 설계에서 고려해야 할 사항 (CDC 이외)

CDC는 "비동기 경계"라는 특정 문제를 다루는 영역이고, RTL 설계 전체를 놓고 보면 고려해야 할 영역이 훨씬 많다. 큰 카테고리별로 정리한다.

---

## 1. Reset 전략

CDC 다음으로 실무에서 가장 많이 버그가 나는 영역.

- **Async assert / Sync de-assert**: reset을 걸 때는 즉시(비동기) 걸리게 하고, 풀 때는 클럭에 동기화해서 풀어야 함. 그냥 비동기 reset을 걸어놓기만 하면 reset이 풀리는 순간 setup/hold 위반이 날 수 있음.
- **Reset domain crossing**: reset 신호 자체도 클럭 도메인이 다르면 CDC처럼 동기화가 필요함.
- **Reset tree 부담**: 큰 SoC에서 global reset을 fan-out 많은 곳에 걸면 reset insertion delay가 커져 reset skew 문제가 생김.
- **Power-on reset vs soft reset 구분**: 어떤 레지스터가 POR에서만 초기화되고, 어떤 게 소프트 리셋에도 초기화돼야 하는지 명확히 설계해야 함.

---

## 2. FSM(상태 머신) 설계

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

## 3. Synthesis-friendly 코딩 (합성 결과를 예측 가능하게)

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

## 4. Timing Closure (Setup/Hold, 일반 타이밍)

- **Critical path 관리**: 조합 로직 depth가 너무 깊으면 파이프라인 스테이지를 추가해서 나눠야 함.
- **Hold time violation**: setup은 클럭을 느리게 하면 해결되지만, hold는 클럭 속도와 무관하게 항상 만족해야 함 — 특히 register-to-register 경로가 너무 짧을 때(0-지연 경로) 발생하기 쉬움.
- **Multicycle path**: 어떤 데이터는 원래 여러 클럭에 걸쳐 안정화되도록 설계되는 경우가 있는데, 이걸 STA에 `set_multicycle_path`로 명시하지 않으면 불필요하게 빡빡한 타이밍 요구가 생김.

---

## 5. Low Power 설계

- **Clock gating**: 안 쓰는 블록의 클럭을 꺼서 dynamic power 절감. 다만 clock gating cell 자체에 glitch가 있으면 안 되므로 표준 ICG(Integrated Clock Gating) cell을 써야 함.

```verilog
// 위험한 수동 clock gating (glitch 위험)
assign gated_clk = clk & enable;

// 안전: 표준 ICG cell 또는 latch 기반 클럭 게이팅 사용
```

- **Power domain (UPF/CPF)**: 여러 전압 도메인을 쓸 경우 level shifter, isolation cell, retention register가 domain 경계마다 필요.
- **Power domain crossing**은 CDC와 유사하게 별도의 정적 검증(UPF lint)이 필요.

---

## 6. Arbitration & Multi-master 설계

- 여러 마스터가 하나의 자원(버스, 메모리)에 동시 접근할 때 **공정성(fairness)**과 **starvation 방지**를 고려한 arbiter 설계 필요 (round-robin, priority-based 등).
- Handshake 프로토콜(예: AXI의 valid/ready)에서 **deadlock 가능성**을 반드시 검토해야 함 — 특히 ready가 valid에 종속되면 안 되는 등 프로토콜 규칙 준수.

---

## 7. 메모리(SRAM/Register File) 설계 고려사항

- **Read-before-write / write-before-read** 동작 정의를 명확히 하고 RTL 모델이 실제 memory compiler IP의 동작과 일치하는지 확인.
- **Memory BIST/redundancy**를 고려한 인터페이스 설계.
- **ECC(에러 정정)**가 필요한 메모리는 인코더/디코더 지연을 파이프라인에 반영.

---

## 8. DFT (Design for Test) 고려사항

- **Scan chain 삽입을 고려한 설계**: 모든 FF가 scan 가능한 형태(scan flop)로 설계 가능해야 함. 비동기 reset/set이 있는 FF는 scan 삽입이 더 까다로움.
- **Test mode에서의 clock/reset 처리**: 여러 클럭 도메인의 scan chain을 어떻게 묶을지(clock domain별로 나눌지) 미리 고려.
- Clock gating cell도 test mode에서는 bypass할 수 있게 설계해야 ATPG(자동 테스트 패턴 생성) 커버리지가 나옴.

---

## 9. 코드 품질 / 검증 관점

- **Lint (기능 lint, CDC lint와는 별개)**: 배열 범위 초과, 부호 없는/있는 비교 오류, 사용되지 않는 신호 등을 정적으로 검사 (Verilator, SpyGlass Lint 등).
- **Coverage (기능/코드 커버리지)**: 시뮬레이션이 RTL의 모든 분기, 모든 상태 전이를 실제로 exercise 했는지 확인.
- **X-propagation 인식 설계**: 시뮬레이션에서 X(unknown)가 실제 하드웨어에서는 특정 값(0 또는 1)으로 resolve되는데, RTL이 이 차이 때문에 시뮬레이션과 실제 동작이 달라지지 않도록 주의 (예: `case`문에서 X를 우연히 특정 분기로 매칭시키는 실수).

---

## 10. 재사용성 / 유지보수 관점

- **파라미터화(parameterization)**: 버스 폭, 깊이 등을 하드코딩하지 않고 `parameter`/`localparam`으로 관리해 재사용성 확보.
- **Naming convention 일관성**: 클럭(`clk_*`), reset(`rst_n_*`), active-low 신호(`*_n`) 등 팀 표준을 지켜야 리뷰/유지보수가 쉬움.
- **Assertion 내장(SVA)**: 설계자가 "이 신호는 이런 조건에서 절대 이렇게 안 된다"는 가정을 RTL에 assertion으로 박아두면, 버그를 시뮬레이션 단계에서 훨씬 빨리 잡을 수 있음.

---

## 요약 표

| 카테고리 | 핵심 이슈 |
|---|---|
| Reset | Async assert / Sync de-assert, reset domain crossing |
| FSM | 불법 상태 복구, encoding 방식 |
| 코딩 스타일 | Latch 방지, blocking/non-blocking 일관성 |
| Timing | Critical path, hold violation, multicycle path |
| Low Power | Clock gating glitch 방지, power domain crossing |
| Arbitration | Fairness, deadlock 방지 |
| Memory | R/W 정책, ECC, BIST 연동 |
| DFT | Scan 가능한 FF 설계, test mode clock/reset |
| 검증 | Lint, coverage, X-propagation |
| 유지보수 | 파라미터화, naming, assertion |
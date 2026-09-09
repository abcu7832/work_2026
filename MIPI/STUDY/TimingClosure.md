Vivado Timing Closure 문제 및 해결 방법

1. 개요

Vivado에서 Timing Closure를 진행할 때는 단순히 Timing Violation을 없애는 것이 목적이 아니라,

설계의 실제 동작 의도에 맞게 모든 timing requirement를 만족시키는 것

이 핵심이다.

일반적인 흐름은 다음과 같다.

RTL
 ↓
Synthesis
 ↓
Implementation
 ↓
Timing Analysis
 ↓
Violation 확인
 ↓
원인 분석
 ↓
RTL / Constraint / Physical 수정
 ↓
Implementation
 ↓
Timing 재확인

⸻

2. Timing Closure에서 자주 발생하는 문제

문제	주요 원인	대표적인 해결 방법
Logic Delay가 큼	Combinational logic depth가 깊음	Pipeline, RTL 구조 변경
Fanout이 큼	하나의 신호가 너무 많은 곳으로 전달	Register duplication, 구조 변경
큰 MUX	복잡한 조건문 / mux tree	RTL 구조 변경, Pipeline
Routing Delay가 큼	배선 거리가 길거나 congestion 발생	Physical optimization, placement 개선
Congestion	Logic이 특정 영역에 과도하게 집중	RTL/placement/constraint 개선
DSP Timing 문제	DSP 연산 경로가 길거나 inference 문제	DSP 사용 확인, Pipeline
BRAM Timing 문제	Memory → Logic 경로가 김	BRAM output register, Pipeline
Clock Constraint 문제	Clock이 잘못 정의됨	create_clock, generated clock 수정
Input/Output Timing 문제	I/O delay constraint 누락/오류	set_input_delay, set_output_delay
여러 Cycle이 필요한 Path	실제 설계상 1 cycle에 끝낼 필요 없음	set_multicycle_path
Timing과 무관한 Path	실제로 timing check가 필요 없음	set_false_path
CDC 문제	서로 다른 clock domain	CDC 구조 및 clock constraint 수정
Hold Violation	Data path가 너무 빠름	Delay insertion, placement/physical optimization
Setup Violation	Data path가 너무 느림	Pipeline, optimization, architecture 변경

⸻

3. Logic Depth가 너무 깊은 경우

문제

하나의 clock cycle 안에 너무 많은 combinational logic이 들어간 경우.

FF1
 ↓
LUT
 ↓
LUT
 ↓
LUT
 ↓
LUT
 ↓
LUT
 ↓
FF2

예를 들어 Clock Period가 5 ns인데 logic delay가 6 ns라면:

Required = 5 ns
Arrival  = 6 ns
Slack = -1 ns

Setup violation이 발생한다.

해결 방법

가장 대표적인 방법은 Pipeline 추가다.

기존

FF
 ↓
Logic A
 ↓
Logic B
 ↓
Logic C
 ↓
FF

변경

FF
 ↓
Logic A
 ↓
FF
 ↓
Logic B
 ↓
FF
 ↓
Logic C
 ↓
FF

Latency는 증가하지만 각 cycle의 timing requirement를 만족하기 쉬워진다.

간단한 예시

// Pipeline 이전
always_ff @(posedge clk) begin
    result <= (a * b) + (c * d);
end
// Pipeline 이후
always_ff @(posedge clk) begin
    mult_a <= a * b;
    mult_b <= c * d;
end
always_ff @(posedge clk) begin
    result <= mult_a + mult_b;
end

⸻

4. Fanout이 너무 큰 경우

문제

하나의 신호가 매우 많은 logic을 구동하는 경우.

             ┌─> Logic 1
             ├─> Logic 2
             ├─> Logic 3
             ├─> Logic 4
FF ──────────┼─> ...
             └─> Logic 1000

Fanout이 높으면 routing delay가 증가할 수 있다.

해결 방법

Register Duplication

하나의 register가 모든 logic을 구동하지 않고 여러 register로 복제한다.

기존:
FF
 ├────────> Logic 1
 ├────────> Logic 2
 ├────────> ...
 └────────> Logic 1000
변경:
        ┌─> FF_A ──> Logic 1~250
FF ─────┼─> FF_B ──> Logic 251~500
        ├─> FF_C ──> Logic 501~750
        └─> FF_D ──> Logic 751~1000

Vivado synthesis/physical optimization이 자동으로 처리할 수도 있지만,
RTL 구조를 변경해서 해결해야 하는 경우도 있다.

⸻

5. 큰 MUX가 있는 경우

문제

복잡한 if, case 또는 조건문으로 인해 매우 큰 MUX tree가 생성되는 경우.

always_comb begin
    case(sel)
        4'd0: y = a;
        4'd1: y = b;
        4'd2: y = c;
        4'd3: y = d;
        // ...
        4'd15: y = p;
    endcase
end

큰 MUX가 critical path에 들어가면 timing이 나빠질 수 있다.

해결 방법

* MUX 구조 변경
* Pipeline 추가
* Critical path 분리
* 조건문 구조 변경
* 필요하면 architecture 자체 변경

예시

기존:
FF
 ↓
16:1 MUX
 ↓
Logic
 ↓
FF
변경:
FF
 ↓
8:1 MUX
 ↓
FF
 ↓
2:1 MUX
 ↓
FF

단, Pipeline 추가는 latency 증가가 발생하므로 기능적인 영향까지 확인해야 한다.

⸻

6. Routing Delay가 큰 경우

문제

Logic 자체의 delay보다 routing delay가 큰 경우.

예:

Logic Delay   = 2.0 ns
Routing Delay = 4.0 ns
----------------------
Total         = 6.0 ns

Clock Period가 5 ns라면 Setup violation이다.

이 경우 logic을 줄이는 것만으로는 해결되지 않을 수 있다.

주요 원인

* Register와 logic의 물리적 거리가 멂
* 높은 fanout
* Congestion
* 특정 영역에 logic이 집중
* placement가 좋지 않음

해결 방법

* Physical optimization
* Placement 개선
* Fanout 감소
* Register duplication
* Congestion 개선
* RTL 구조 변경

Vivado에서는 implementation 이후 physical optimization을 활용할 수 있다.

phys_opt_design

⸻

7. Congestion 문제

문제

FPGA의 특정 영역에 logic/routing resource가 과도하게 몰리는 경우.

+-----------------------+
|                       |
|     Logic Logic       |
|     Logic Logic       |
|     Logic Logic       |
|     Logic Logic       |
|     Congestion !!!    |
|                       |
+-----------------------+

Congestion이 심하면 routing delay가 증가하고 timing이 악화될 수 있다.

해결 방법

* Logic 분산
* Placement constraint 검토
* 불필요한 hierarchy/region constraint 제거
* RTL 구조 변경
* Pipeline 추가
* Resource utilization 감소
* Physical optimization

예시

기존:
Region A
████████████████████
████████████████████
████████████████████
변경:
Region A       Region B
████████       ████████
████████       ████████

⸻

8. DSP Timing 문제

문제

Multiplier/Adder 등이 DSP block으로 구현되더라도 DSP 내부 또는 DSP와 주변 logic 사이의 timing이 문제가 될 수 있다.

FF
 ↓
DSP
 ↓
Logic
 ↓
FF

해결 방법

* DSP inference가 제대로 되었는지 확인
* DSP 내부 pipeline 사용
* DSP 출력 register 사용
* 연산을 여러 cycle로 분리

예시

기존:
FF → DSP → ADD → FF
변경:
FF → DSP → FF → ADD → FF

⸻

9. BRAM Timing 문제

문제

Block RAM에서 데이터를 읽은 후 logic을 거쳐 register까지 가는 경로가 긴 경우.

FF
 ↓
BRAM
 ↓
Large Logic
 ↓
FF

해결 방법

BRAM output register를 사용하거나 pipeline을 추가한다.

기존:
BRAM → Logic → FF
변경:
BRAM → FF → Logic → FF

또는 BRAM의 registered output을 활용한다.

⸻

10. Clock Constraint 문제

문제

Clock constraint가 잘못되어 있으면 timing report 자체를 신뢰하기 어렵다.

예를 들어 실제 clock이 200 MHz인데:

create_clock -period 10.000 [get_ports clk]

로 설정했다면 실제 5 ns clock인데 10 ns로 분석하게 된다.

해결 방법

실제 clock specification과 XDC를 일치시킨다.

create_clock \
    -period 5.000 \
    [get_ports clk]

200 MHz clock:

Frequency = 200 MHz
Period    = 5 ns

⸻

11. Generated Clock 문제

PLL/MMCM 등을 사용하는 경우 생성된 clock의 관계를 제대로 정의해야 한다.

Input Clock
    ↓
MMCM
 ├──> clk_100M
 ├──> clk_200M
 └──> clk_50M

Generated clock 관계가 잘못되면 timing analysis가 잘못될 수 있다.

해결 방법

Vivado가 clock을 제대로 추론하는지 확인하고 필요한 경우 generated clock constraint를 설정한다.

예:

create_generated_clock ...

실제 설계에서는 Vivado가 자동으로 생성하는 clock constraint도 반드시 확인하는 것이 좋다.

⸻

12. Input Delay 문제

문제

FPGA 외부에서 FPGA로 들어오는 input timing constraint가 없는 경우.

External Device
      ↓
     FPGA
      ↓
     Logic
      ↓
      FF

FPGA 내부 clock만 지정한다고 해서 외부 device와의 timing까지 정확하게 분석되는 것은 아니다.

해결 방법

외부 device의 timing specification을 기반으로 input delay를 정의한다.

예:

set_input_delay -clock clk 2.0 [get_ports data_in]

의미는 외부 device에서 data_in으로 들어오는 데이터의 timing 조건을 Vivado에 알려주는 것이다.

⸻

13. Output Delay 문제

Output도 마찬가지다.

FF
 ↓
FPGA Logic
 ↓
Output Port
 ↓
External Device

외부 device가 FPGA output을 언제까지 받아야 하는지를 constraint로 알려줘야 한다.

예:

set_output_delay -clock clk 2.0 [get_ports data_out]

정확한 값은 실제 interface specification에 따라 결정해야 한다.

⸻

14. Multicycle Path

문제

어떤 path가 실제 설계상 한 clock cycle 안에 완료될 필요가 없는 경우.

예:

Clock = 5 ns
FF1 → Long Logic → FF2

Logic delay가 7 ns라면 일반적인 1-cycle timing에서는 violation이다.

하지만 architecture상 FF2가 2번째 clock edge에서 데이터를 받아도 된다면 2-cycle path로 정의할 수 있다.

해결 방법

set_multicycle_path 2 -setup \
    -from [get_cells FF1] \
    -to [get_cells FF2]
set_multicycle_path 1 -hold \
    -from [get_cells FF1] \
    -to [get_cells FF2]

개념적으로:

1-cycle path:
FF1 |----------------| FF2
        5 ns
2-cycle path:
FF1 |-------------------------------| FF2
               10 ns

주의

set_multicycle_path는 logic을 빠르게 만드는 명령이 아니다.

Logic Delay = 7 ns
Multicycle 적용 전
Required = 5 ns
Slack    = -2 ns
Multicycle 2 적용 후
Required ≈ 10 ns
Slack    ≈ +3 ns

즉 timing requirement를 변경하는 것이다.

따라서 실제 설계가 2 cycle을 허용할 때만 사용해야 한다.

⸻

15. False Path

문제

Timing analysis를 할 필요가 없는 path가 존재하는 경우.

대표적으로 asynchronous clock domain 사이의 path가 있다.

Clock A Domain
FF_A
 ↓
CDC Logic
 ↓
FF_B
Clock B Domain

두 clock이 서로 asynchronous하다면 일반적인 synchronous timing path로 분석하면 안 된다.

해결 방법

설계 의도에 맞게 clock relationship 또는 false path를 정의한다.

예:

set_false_path \
    -from [get_clocks clk_a] \
    -to [get_clocks clk_b]

주의

False path는 매우 강력한 constraint다.

Timing violation 발생
        ↓
set_false_path
        ↓
Violation 사라짐

처럼 보일 수 있지만 실제 hardware가 안전해진 것은 아니다.

따라서 정말 timing analysis가 필요 없는 path인지 반드시 확인해야 한다.

⸻

16. CDC 문제

문제

서로 다른 clock domain 사이에서 데이터를 직접 전달하는 경우.

clk_A
  ↓
FF_A ───────────────> FF_B
                       ↑
                      clk_B

clock phase/frequency 관계가 없으면 metastability가 발생할 수 있다.

해결 방법

일반적인 1-bit control signal이라면 synchronizer를 사용한다.

clk_A                    clk_B
FF_A
 ↓
 ┌─────┐
 │ FF  │
 └─────┘
    ↓
 ┌─────┐
 │ FF  │
 └─────┘
    ↓
  Logic

Multi-bit data라면 상황에 따라:

* Handshake
* Async FIFO
* Gray code
* CDC-specific architecture

등을 사용한다.

⸻

17. Setup Violation

문제

데이터가 capture edge까지 도착하지 못한다.

Launch FF
   ↓
   Logic
   ↓
   FF

예:

Clock Period = 5 ns
Data Delay   = 6 ns
Slack = -1 ns

해결 방법

대표적인 방법:

1. Pipeline
2. Logic depth 감소
3. Fanout 감소
4. MUX 구조 변경
5. DSP/BRAM pipeline
6. Placement 개선
7. Physical optimization
8. 필요하면 architecture 변경
9. 실제로 multi-cycle이면 set_multicycle_path

⸻

18. Hold Violation

문제

Setup과 반대로 데이터가 너무 빨리 도착하는 경우다.

Launch FF
   ↓
아주 짧은 Logic
   ↓
Capture FF

예:

Data가 capture FF에
너무 빨리 도착
        ↓
Hold violation

해결 방법

Setup violation과 접근 방법이 다르다는 점이 중요하다.

대표적인 방법:

* Data path에 delay 추가
* Placement 조정
* Physical optimization
* Clock skew 개선

FPGA에서는 구현 도구가 hold fixing을 수행하는 경우가 많다.

중요한 점

Hold violation을 해결하려고 무조건 pipeline을 추가하는 것은 적절하지 않다.

⸻

19. Setup vs Hold

구분	Setup	Hold
문제	데이터가 늦게 도착	데이터가 너무 빨리 도착
주요 원인	Logic/Routing delay가 큼	Data path가 너무 짧거나 clock skew
대표 해결	Pipeline, optimization	Delay insertion, physical optimization
Clock Period 영향	매우 큼	상대적으로 작음
Multicycle 관련	주로 Setup	Hold constraint도 함께 고려

⸻

20. Timing Closure 문제를 만났을 때의 실전 순서

Step 1. Timing Summary 확인

먼저 다음을 확인한다.

WNS
TNS
WHW
THS

특히:

WNS < 0

이면 setup violation이 존재한다.

WHS < 0

이면 hold violation이 존재한다.

⸻

Step 2. Worst Path 확인

Report Timing
     ↓
Startpoint
     ↓
Logic
     ↓
Routing
     ↓
Endpoint

을 확인한다.

⸻

Step 3. Logic Delay와 Routing Delay 분리

예:

Data Path Delay = 6.5 ns
Logic Delay   = 2.0 ns
Routing Delay = 4.5 ns

이 경우 단순히 RTL logic을 줄이는 것보다 placement, fanout, congestion 등을 먼저 의심할 수 있다.

반대로:

Logic Delay   = 5.5 ns
Routing Delay = 1.0 ns

이라면 RTL 구조나 pipeline이 핵심일 가능성이 높다.

⸻

21. 상황별 빠른 판단표

Case A

Logic Delay가 큼

→ RTL / Pipeline 검토

FF
 ↓
Logic
 ↓
Logic
 ↓
Logic
 ↓
FF

⸻

Case B

Routing Delay가 큼

→ Fanout / Placement / Congestion 검토

Logic Delay   = 1 ns
Routing Delay = 5 ns

⸻

Case C

실제로 2 cycle이 허용됨

→ set_multicycle_path

FF1 → Logic → FF2
        2 cycles

⸻

Case D

Timing analysis 자체가 필요 없음

→ set_false_path

단, 정말 false path인지 확인한다.

⸻

Case E

Clock domain이 다름

→ CDC 구조와 clock relationship 검토

clk_A → CDC → clk_B

⸻

Case F

외부 device와 interface timing이 존재

→ set_input_delay / set_output_delay

⸻

22. Constraint 명령어 한눈에 보기

Constraint	의미
create_clock	기본 clock 정의
create_generated_clock	생성된 clock 정의
set_input_delay	외부 → FPGA input timing 정의
set_output_delay	FPGA → 외부 output timing 정의
set_multicycle_path	여러 clock cycle 허용
set_false_path	timing analysis에서 path 제외
set_max_delay	특정 path의 최대 delay 지정
set_min_delay	특정 path의 최소 delay 지정
set_clock_groups	clock group 간 timing 관계 지정

⸻

23. 가장 중요한 원칙

Timing violation이 발생했다고 해서 다음 순서로 바로 가면 안 된다.

Timing violation
      ↓
set_false_path
      ↓
PASS

또는

Timing violation
      ↓
set_multicycle_path
      ↓
PASS

이것은 위험한 접근이다.

올바른 순서는:

Timing Violation
       ↓
어떤 Path인가?
       ↓
왜 늦거나 빠른가?
       ↓
실제 설계 의도는 무엇인가?
       ↓
       ├── RTL 문제
       │     ↓
       │   Pipeline / Logic 변경
       │
       ├── Physical 문제
       │     ↓
       │   Placement / Fanout / Phys Opt
       │
       ├── 실제 Multi-cycle
       │     ↓
       │   set_multicycle_path
       │
       ├── 실제 False Path
       │     ↓
       │   set_false_path
       │
       └── Constraint 문제
             ↓
           XDC 수정

⸻

24. 핵심 요약

Timing Closure에서 가장 먼저 기억할 것은 다음 네 가지다.

1. Setup Violation

데이터가 너무 늦게 도착한다.

→ Pipeline
→ Logic optimization
→ Fanout 감소
→ Placement/Physical optimization

2. Hold Violation

데이터가 너무 빨리 도착한다.

→ Delay insertion
→ Placement
→ Physical optimization

3. Multicycle Path

데이터가 여러 cycle 후 도착해도 실제 기능상 문제가 없다.

set_multicycle_path 2 -setup ...
set_multicycle_path 1 -hold ...

4. False Path

해당 path는 timing analysis 대상이 아니다.

set_false_path ...

⸻

25. 한 문장으로 정리

Timing Closure는 “Timing violation을 없애는 작업”이 아니라, 실제 설계 의도에 맞는 timing constraint를 정의하고, 필요한 경우 RTL/architecture/physical implementation을 변경하여 모든 유효한 timing path를 만족시키는 작업이다.
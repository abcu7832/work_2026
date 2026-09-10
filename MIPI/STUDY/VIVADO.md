# Vivado 완전 가이드

Vivado는 AMD(구 Xilinx)의 FPGA 설계 통합 환경(IDE)으로, RTL 작성부터 Synthesis, Implementation, Bitstream 생성 및 FPGA 프로그래밍까지 전체 설계 흐름을 지원한다. 이 문서는 Vivado 설계 흐름의 각 단계를 실전 중심으로 정리한다.

---

## 목차

1. [RTL 작성](#1-rtl-작성)
2. [XDC 작성](#2-xdc-작성)
3. [각종 레포트 종류 및 분석 방법](#3-각종-레포트-종류-및-분석-방법)
4. [Synthesis](#4-synthesis)
5. [Implementation](#5-implementation)
6. [FPGA Bitstream](#6-fpga-bitstream)

---

## 1. RTL 작성

### 1.1 프로젝트 구조

Vivado 프로젝트를 생성하면 기본적으로 아래 디렉토리 구조가 만들어진다.

```
my_project/
├── my_project.xpr          # 프로젝트 파일 (XML 형식)
├── my_project.srcs/
│   ├── sources_1/          # RTL 소스 파일 (Verilog/VHDL/SystemVerilog)
│   │   └── new/
│   │       └── top.v
│   ├── constrs_1/          # XDC 제약 파일
│   │   └── new/
│   │       └── top.xdc
│   └── sim_1/              # 시뮬레이션 소스 (TB)
│       └── new/
│           └── tb_top.v
├── my_project.runs/
│   ├── synth_1/            # Synthesis 결과
│   └── impl_1/             # Implementation 결과
└── my_project.sim/         # 시뮬레이션 결과
```

**프로젝트 모드 vs 비프로젝트(Non-project) 모드**

- **프로젝트 모드**: GUI 기반, `.xpr` 파일로 관리. 초보자 친화적.
- **비프로젝트 모드**: Tcl 스크립트로 전체 흐름을 직접 제어. CI/CD 자동화, 대형 팀 협업에 적합.

### 1.2 Verilog RTL 작성 예시

Vivado는 Verilog, VHDL, SystemVerilog를 지원한다. 아래는 실전에서 쓰이는 파라미터화된 동기 FIFO 예시다.

```verilog
// sync_fifo.v
module sync_fifo #(
    parameter DATA_WIDTH = 8,
    parameter DEPTH      = 16,
    parameter ADDR_WIDTH = $clog2(DEPTH)
)(
    input  wire                   clk,
    input  wire                   rst_n,
    // Write 포트
    input  wire                   wr_en,
    input  wire [DATA_WIDTH-1:0]  wr_data,
    output wire                   full,
    // Read 포트
    input  wire                   rd_en,
    output reg  [DATA_WIDTH-1:0]  rd_data,
    output wire                   empty
);

    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];
    reg [ADDR_WIDTH:0]   wr_ptr, rd_ptr;

    assign full  = (wr_ptr[ADDR_WIDTH] != rd_ptr[ADDR_WIDTH]) &&
                   (wr_ptr[ADDR_WIDTH-1:0] == rd_ptr[ADDR_WIDTH-1:0]);
    assign empty = (wr_ptr == rd_ptr);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
        end else begin
            if (wr_en && !full) begin
                mem[wr_ptr[ADDR_WIDTH-1:0]] <= wr_data;
                wr_ptr <= wr_ptr + 1'b1;
            end
            if (rd_en && !empty) begin
                rd_data <= mem[rd_ptr[ADDR_WIDTH-1:0]];
                rd_ptr  <= rd_ptr + 1'b1;
            end
        end
    end

endmodule
```

### 1.3 주요 설정 및 Language 옵션

**소스 파일 추가 방법**
- GUI: `Sources` 창 → 우클릭 → `Add Sources` → `Add or create design sources`
- Tcl:
```tcl
add_files -norecurse {./src/sync_fifo.v ./src/top.v}
set_property top top [current_fileset]
update_compile_order -fileset sources_1
```

**언어 표준 설정**

SystemVerilog 사용 시 파일 속성을 명시해야 한다.
```tcl
set_property file_type SystemVerilog [get_files top.sv]
```

**IP 코어 사용 (IP Catalog)**

Vivado IP Catalog에서 FIFO Generator, BRAM, PLL(MMCM), AXI Interconnect 등 표준 IP를 생성해 프로젝트에 추가할 수 있다.
```tcl
# Tcl로 IP 생성 예시 (FIFO Generator)
create_ip -name fifo_generator -vendor xilinx.com -library ip -version 13.2 -module_name fifo_gen_0
set_property -dict [list \
    CONFIG.Fifo_Implementation {Independent_Clocks_Block_RAM} \
    CONFIG.Input_Data_Width {32} \
    CONFIG.Input_Depth {512} \
] [get_ips fifo_gen_0]
generate_target all [get_ips fifo_gen_0]
```

### 1.4 Top-level 설계 예시

```verilog
// top.v - 여러 모듈을 묶는 최상위
module top (
    input  wire        clk_p,    // LVDS 차동 클럭 입력
    input  wire        clk_n,
    input  wire        rst_ext_n,
    input  wire [7:0]  din,
    output wire [7:0]  dout,
    output wire        led
);

    wire clk_sys;   // MMCM 출력 내부 클럭
    wire locked;
    wire rst_n = locked & rst_ext_n;

    // MMCM 인스턴스 (PLL 역할)
    clk_wiz_0 u_clk_wiz (
        .clk_in1_p (clk_p),
        .clk_in1_n (clk_n),
        .clk_out1  (clk_sys),
        .locked    (locked),
        .reset     (~rst_ext_n)
    );

    sync_fifo #(
        .DATA_WIDTH(8),
        .DEPTH(64)
    ) u_fifo (
        .clk     (clk_sys),
        .rst_n   (rst_n),
        .wr_en   (1'b1),
        .wr_data (din),
        .rd_en   (1'b1),
        .rd_data (dout),
        .full    (),
        .empty   ()
    );

    assign led = locked;

endmodule
```

---

## 2. XDC 작성

XDC(Xilinx Design Constraints)는 Vivado에서 타이밍 제약, I/O 핀 배정, 타이밍 예외 등을 정의하는 파일이다. SDC(Synopsys Design Constraints) 포맷 기반이며, 추가로 Xilinx 전용 명령어(`set_property` 등)를 포함한다.

### 2.1 클럭 제약 (create_clock)

클럭 제약은 XDC에서 가장 중요한 항목이다. STA(Static Timing Analysis)의 기준이 된다.

```xdc
# 기본 단일 클럭 (100MHz = 10ns 주기)
create_clock -period 10.000 -name sys_clk -waveform {0.000 5.000} [get_ports clk]

# 차동 클럭 (LVDS) - clk_p 포트만 기준으로 정의
create_clock -period 10.000 -name sys_clk [get_ports clk_p]

# 여러 클럭 도메인 (125MHz + 200MHz)
create_clock -period 8.000  -name clk_125 [get_ports clk_125_p]
create_clock -period 5.000  -name clk_200 [get_ports clk_200_p]
```

**MMCM/PLL 출력 클럭 — create_generated_clock**

IP에서 생성된 파생 클럭도 명시해야 툴이 올바르게 타이밍을 분석한다. 일반적으로 `clk_wiz` IP가 자동으로 XDC를 생성하지만, 커스텀 분주기를 직접 만들 때는 수동으로 작성해야 한다.

```xdc
# MMCM 출력 150MHz (소스 클럭의 3/2배)
create_generated_clock -name clk_150 \
    -source [get_pins u_clk_wiz/inst/mmcme4_adv_inst/CLKIN1] \
    -multiply_by 3 -divide_by 2 \
    [get_pins u_clk_wiz/inst/mmcme4_adv_inst/CLKOUT0]

# 레지스터 분주 클럭 (div2)
create_generated_clock -name clk_div2 \
    -source [get_ports clk] \
    -divide_by 2 \
    [get_pins u_clk_div/q_reg/Q]
```

### 2.2 I/O 핀 배정 및 전기적 특성

```xdc
# 핀 위치 배정
set_property PACKAGE_PIN E3  [get_ports clk]
set_property PACKAGE_PIN C12 [get_ports rst_ext_n]
set_property PACKAGE_PIN H17 [get_ports led]

# I/O 표준 설정 (LVCMOS33: 3.3V, LVCMOS18: 1.8V)
set_property IOSTANDARD LVCMOS33 [get_ports clk]
set_property IOSTANDARD LVCMOS33 [get_ports rst_ext_n]
set_property IOSTANDARD LVCMOS33 [get_ports led]

# 버스 신호 일괄 설정
set_property PACKAGE_PIN {J15 L16 M13 R15 R17 T18 U18 R18} [get_ports {din[*]}]
set_property IOSTANDARD LVCMOS33 [get_ports {din[*]}]

# 출력 드라이브 강도 / 슬루 레이트
set_property DRIVE     8    [get_ports led]
set_property SLEW      SLOW [get_ports led]

# Pull-up / Pull-down
set_property PULLUP    true [get_ports rst_ext_n]
```

**LVDS 차동 쌍**
```xdc
set_property PACKAGE_PIN  D4  [get_ports clk_p]
set_property PACKAGE_PIN  C4  [get_ports clk_n]
set_property IOSTANDARD   LVDS [get_ports clk_p]
set_property IOSTANDARD   LVDS [get_ports clk_n]
```

### 2.3 입출력 타이밍 제약 (set_input_delay / set_output_delay)

보드 레벨에서의 신호 도착/출발 타이밍을 정의한다. 외부 소자(ADC, DAC, 메모리 컨트롤러 등)와의 인터페이스 타이밍 분석에 필수다.

```xdc
# 입력 지연: 보드 지연 + 소자 출력 지연 = 최대 3ns, 최소 1ns
set_input_delay -clock sys_clk -max 3.000 [get_ports {din[*]}]
set_input_delay -clock sys_clk -min 1.000 [get_ports {din[*]}]

# 출력 지연: 수신 소자의 setup = 2ns, hold = 0.5ns
set_output_delay -clock sys_clk -max  2.000 [get_ports {dout[*]}]
set_output_delay -clock sys_clk -min -0.500 [get_ports {dout[*]}]
```

### 2.4 타이밍 예외 제약

#### set_false_path — 타이밍 분석 제외

CDC synchronizer 경로, 비동기 reset, 테스트 신호 등 STA가 의미 없는 경로에 사용한다.

```xdc
# CDC 경로 — clk_125에서 clk_200으로 넘어가는 경로 제외
set_false_path -from [get_clocks clk_125] -to [get_clocks clk_200]
set_false_path -from [get_clocks clk_200] -to [get_clocks clk_125]

# 특정 레지스터에서 출발하는 경로 제외 (reset synchronizer)
set_false_path -from [get_pins u_rst_sync/rst_reg[*]/C]

# 비동기 리셋 포트
set_false_path -from [get_ports rst_ext_n]
```

#### set_max_delay — 최대 지연 제약 (CDC 권장)

`set_false_path`는 STA 분석을 완전히 끄지만, `set_max_delay -datapath_only`는 setup 분석은 유지하면서 클럭 스큐를 무시한다. CDC synchronizer에 더 정밀한 제약이다.

```xdc
# CDC 경로에 1클럭 주기(목적지 기준) 안에 들어오도록 제약
set_max_delay -datapath_only -from [get_clocks clk_125] \
    -to [get_pins u_sync/meta_ff_reg/D] 8.000
```

#### set_multicycle_path — 멀티사이클 경로

```xdc
# 특정 경로에 2클럭 주기를 허용 (setup: 2사이클, hold: 1사이클 기본)
set_multicycle_path -setup 2 \
    -from [get_cells u_mac/reg_a_reg[*]] \
    -to   [get_cells u_mac/reg_result_reg[*]]
set_multicycle_path -hold  1 \
    -from [get_cells u_mac/reg_a_reg[*]] \
    -to   [get_cells u_mac/reg_result_reg[*]]
```

### 2.5 물리적 제약

```xdc
# Pblock — 특정 모듈을 FPGA의 특정 영역에 배치 고정
create_pblock pblock_fifo
add_cells_to_pblock [get_pblocks pblock_fifo] [get_cells u_fifo]
resize_pblock [get_pblocks pblock_fifo] -add {SLICE_X0Y0:SLICE_X15Y31}

# CDC synchronizer FF 인접 배치 (ASYNC_REG 속성)
set_property ASYNC_REG TRUE [get_cells {u_sync/meta_ff_reg u_sync/sync_ff_reg}]

# LOC — 특정 셀을 특정 사이트에 고정
set_property LOC RAMB36_X0Y0 [get_cells u_bram/inst]
```

### 2.6 XDC 작성 순서 권장

```
1. create_clock / create_generated_clock   (클럭 정의)
2. set_input_delay / set_output_delay      (I/O 타이밍)
3. set_false_path / set_max_delay          (타이밍 예외 — CDC, reset)
4. set_multicycle_path                     (멀티사이클)
5. set_property PACKAGE_PIN / IOSTANDARD   (핀 배정 및 전기 특성)
6. 물리적 제약 (Pblock, ASYNC_REG 등)
```

---

## 3. 각종 레포트 종류 및 분석 방법

Vivado는 Synthesis와 Implementation 각 단계에서 다양한 레포트를 생성한다. 레포트를 제대로 읽어야 문제를 빠르게 찾을 수 있다.

### 3.1 Timing Report (타이밍 레포트)

가장 중요한 레포트. Setup/Hold 위반 여부, Worst Negative Slack(WNS), Total Negative Slack(TNS)을 확인한다.

**레포트 생성**
```tcl
# Implementation 후 타이밍 레포트 생성
report_timing_summary -delay_type min_max -report_unconstrained \
    -check_timing_verbose -max_paths 10 -input_pins \
    -file timing_summary.rpt

# 특정 경로 상세 레포트
report_timing -from [get_cells u_fifo/wr_ptr_reg[*]] \
              -to   [get_cells u_fifo/mem_reg[*]] \
              -max_paths 5 -nworst 1 -delay_type max \
              -file timing_detail.rpt
```

**레포트 읽는 방법**

```
Design Timing Summary
---------------------
WNS(ns)  TNS(ns)  TNS Failing Endpoints  WHS(ns)  THS(ns)
-------  -------  ---------------------  -------  -------
  0.312    0.000                      0    0.045    0.000
```

- **WNS (Worst Negative Slack)**: 가장 타이트한 경로의 여유 시간. **양수면 timing met**, 음수면 위반.
- **TNS (Total Negative Slack)**: 모든 위반 경로의 slack 합산. 0이면 전체 OK.
- **WHS**: Hold 여유. 이것도 양수여야 함.

**경로 상세 분석 예시**

```
Path Group: sys_clk
Path Type: Setup (Max at Slow Process Corner)

Startpoint: u_fifo/wr_ptr_reg[3] (rising edge-triggered flip-flop clocked by sys_clk)
Endpoint:   u_mac/result_reg[7]   (rising edge-triggered flip-flop clocked by sys_clk)

    Delay Type         Incr(ns)   Path(ns)
    -------------------------------------------
    clock sys_clk        0.000      0.000 r
    input delay                     ...
    FDRE (Prop_FDRE_C_Q) 0.141      0.141 r   <-- FF 전파 지연
    net (fanout=4)       0.312      0.453       <-- 배선 지연
    LUT6 (Prop_LUT6_I0_O)0.124     0.577 r    <-- 조합 로직 지연
    ...
    FDRE (Setup_FDRE_C_D) -0.058            r  <-- FF setup 요구
    -------------------------------------------
    required time                   9.942
    arrival time                   -9.630
    -------------------------------------------
    slack                           0.312      <-- 여유 (양수: OK)
```

**분석 포인트**
- Slack이 음수인 경우: 배선 지연(net delay)이 큰지, 조합 로직 depth가 깊은지 확인.
- 조합 로직이 깊으면 파이프라인 스테이지 추가, 혹은 RTL 재구조화 필요.
- 배선 지연이 크면 Pblock으로 관련 셀들을 인접 배치.

### 3.2 Utilization Report (자원 사용량 레포트)

```tcl
report_utilization -file utilization.rpt
report_utilization -hierarchical -file utilization_hier.rpt  # 계층별
```

**레포트 예시**

```
+----------------------------+-------+-------+--------+--------+
|          Site Type         |  Used | Fixed | Avail  | Util%  |
+----------------------------+-------+-------+--------+--------+
| Slice LUTs                 |  3421 |     0 |  53200 |   6.43 |
|   LUT as Logic             |  3215 |     0 |  53200 |   6.04 |
|   LUT as Memory            |   206 |     0 |  17400 |   1.18 |
| Slice Registers            |  4108 |     0 | 106400 |   3.86 |
|   Register as Flip Flop    |  4108 |     0 | 106400 |   3.86 |
| F7 Muxes                   |    64 |     0 |  26600 |   0.24 |
| Block RAM Tile             |     8 |     0 |    140 |   5.71 |
| DSPs                       |    12 |     0 |    220 |   5.45 |
| Bonded IOB                 |    24 |    24 |    200 |  12.00 |
+----------------------------+-------+-------+--------+--------+
```

**분석 포인트**
- LUT 사용률이 80% 초과 시 P&R(Place & Route)이 어려워지고 타이밍 closure 난이도가 급격히 상승.
- `LUT as Memory`가 의도보다 많으면 RTL의 배열이 distributed RAM으로 추론된 것 — Block RAM으로 유도하려면 `(* ram_style = "block" *)` 속성을 추가.
- BRAM/DSP는 전용 자원으로 LUT로 대체되면 면적/타이밍 모두 악화.

### 3.3 Power Report (전력 레포트)

```tcl
report_power -file power.rpt
```

**레포트 예시**

```
Power Summary
--------------
Total On-Chip Power:   0.842 W
  Dynamic Power:       0.621 W   (73.7%)
    Clocks:            0.112 W   (18.0%)
    Logic:             0.089 W   (14.3%)
    Signals:           0.156 W   (25.1%)
    BRAM:              0.064 W   (10.3%)
    IO:                0.200 W   (32.2%)
  Static Power:        0.221 W   (26.3%)
Junction Temperature:  42.3 °C
```

**분석 포인트**
- IO 전력이 높은 경우: 불필요하게 높은 Drive 강도 또는 미사용 IO에 상시 토글 신호가 들어가는 것인지 확인.
- Clock 전력이 높은 경우: 불필요한 클럭 버퍼, clock gating이 누락된 블록이 있는지 확인.
- Junction Temperature가 높으면 발열 위험 — 열 설계 검토 필요.
- **주의**: Power Report는 활성화율(activity)을 가정해서 계산하므로, `.saif` 파일(시뮬레이션 토글 데이터)을 입력하면 더 정확해진다.

```tcl
# 시뮬레이션 기반 정확한 전력 분석
read_saif ./sim/activity.saif
report_power -file power_accurate.rpt
```

### 3.4 DRC Report (설계 규칙 검사)

```tcl
report_drc -file drc.rpt
```

**주요 DRC 항목**

| 규칙 코드 | 설명 | 심각도 |
|---|---|---|
| `NSTD-1` | IOSTANDARD가 설정되지 않은 포트 존재 | Critical |
| `UCIO-1` | 제약 없는 I/O 포트 | Critical |
| `CFGBVS-1` | CFGBVS/CONFIG_VOLTAGE 미설정 | Warning |
| `AVAL-3` | 사용 가능한 자원 초과 | Critical |
| `RTSTAT-10` | Routing 자원 포화 | Warning |

DRC 에러가 있으면 Bitstream 생성이 차단된다 (Critical 등급). Warning은 경우에 따라 waiver 처리 가능하다.

### 3.5 Clock Interaction Report

```tcl
report_clock_interaction -file clock_interaction.rpt
```

비동기 CDC 경로가 있는데 `set_false_path` 또는 `set_max_delay`가 없으면 **unsafe** 경고가 뜬다. XDC에서 CDC 예외를 제대로 설정했는지 검증하는 용도로 사용한다.

```
Clock Pair          Inter-Clock Constraints   Safe/Unsafe
-------------------------------------------------------------
clk_125 -> clk_200  set_false_path applied     SAFE
clk_200 -> clk_sys  No constraint              UNSAFE  <-- 문제
```

### 3.6 Methodology Report

```tcl
report_methodology -file methodology.rpt
```

CDC, timing, coding 관행에 대한 추가적인 방법론 검사. `set_false_path`를 단방향으로만 설정한 경우, ASYNC_REG 속성 누락 등을 잡아준다.

### 3.7 레포트 자동 생성 Tcl 스크립트

```tcl
# Implementation 후 모든 주요 레포트 일괄 생성
set rpt_dir "./reports"
file mkdir $rpt_dir

report_timing_summary  -file $rpt_dir/timing_summary.rpt
report_timing          -max_paths 20 -file $rpt_dir/timing_paths.rpt
report_utilization     -hierarchical -file $rpt_dir/utilization.rpt
report_power           -file $rpt_dir/power.rpt
report_drc             -file $rpt_dir/drc.rpt
report_clock_interaction -file $rpt_dir/clock_interaction.rpt
report_methodology     -file $rpt_dir/methodology.rpt
```

---

## 4. Synthesis

Synthesis(합성)는 RTL Verilog/VHDL 코드를 FPGA의 논리 게이트(LUT, FF, BRAM, DSP 등) 수준의 netlist로 변환하는 과정이다.

### 4.1 GUI에서 Synthesis 실행

`Flow Navigator` → `Synthesis` → `Run Synthesis` 클릭.

완료 후 `Open Synthesized Design`을 선택하면 합성 결과 netlist와 Schematic을 확인할 수 있다.

### 4.2 Tcl로 Synthesis 실행

```tcl
# 프로젝트 모드
open_project my_project.xpr
launch_runs synth_1 -jobs 8
wait_on_run synth_1

# 합성 완료 여부 확인
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    error "Synthesis failed"
}

# 합성 결과 열기
open_run synth_1 -name synth_1
```

비프로젝트 모드:
```tcl
# 소스 읽기
read_verilog [glob ./src/*.v]
read_xdc ./constr/top.xdc

# 합성 실행
synth_design -top top -part xc7a35tcpg236-1

# 결과 저장
write_checkpoint -force ./checkpoint/post_synth.dcp
```

### 4.3 Synthesis 주요 옵션

```tcl
synth_design \
    -top        top              \  # Top-level 모듈 이름
    -part       xc7a35tcpg236-1  \  # 타겟 디바이스
    -flatten_hierarchy rebuilt   \  # 계층 평탄화 (none/rebuilt/full)
    -gated_clock_conversion off  \  # clock gating 자동 변환
    -bufg        12              \  # 최대 BUFG 사용 수
    -directive   AreaOptimized_high  # 합성 전략
```

**`-flatten_hierarchy` 옵션 선택 가이드**

| 옵션 | 설명 | 권장 상황 |
|---|---|---|
| `none` | 계층 유지 | 계층별 타이밍 분석이 필요할 때 |
| `rebuilt` (기본) | 합성 후 계층 재구성 | 일반적 용도 |
| `full` | 완전 평탄화 | QoR 최적화 극대화 필요 시 |

**`-directive` 합성 전략**

| 전략 | 설명 |
|---|---|
| `default` | 기본 합성 |
| `AreaOptimized_high` | 면적 최소화 우선 |
| `AreaOptimized_medium` | 면적 절충 |
| `AlternateRoutability` | 배선 혼잡도 감소 |
| `PerformanceOptimized` | 타이밍 성능 우선 |
| `RuntimeOptimized` | 합성 시간 단축 (QoR 희생) |

### 4.4 합성 결과 확인

```tcl
# 합성 후 타이밍 estimate (P&R 전이므로 참고 수준)
report_timing_summary -no_header -pathgroups none

# 자원 사용량
report_utilization

# Schematic 확인 (GUI)
show_schematic [get_nets clk]
```

**합성 경고 메시지 주요 유형**

| 메시지 | 의미 | 조치 |
|---|---|---|
| `[Synth 8-3331] Sequential element ... is unused` | 불필요한 FF (dead logic) | RTL 정리 |
| `[Synth 8-327] inferring latch for variable ...` | 의도치 않은 latch 생성 | RTL 수정 (모든 분기 채우기) |
| `[Synth 8-3919] Null Assignment ...` | X/Z 대입 | RTL 검토 |
| `[Synth 8-5858] ... has a constant value of ...` | 상수로 최적화된 신호 | 의도적인지 확인 |

---

## 5. Implementation

Implementation은 Synthesis가 만든 논리 netlist를 실제 FPGA 칩의 물리적 자원에 배치(Place)하고 배선(Route)하는 과정이다.

### 5.1 Implementation 실행

**GUI**: `Flow Navigator` → `Implementation` → `Run Implementation`

**Tcl (프로젝트 모드)**:
```tcl
launch_runs impl_1 -jobs 8
wait_on_run impl_1

if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    error "Implementation failed"
}

open_run impl_1 -name impl_1
```

**Tcl (비프로젝트 모드)**:
```tcl
# 합성 체크포인트로부터 시작
open_checkpoint ./checkpoint/post_synth.dcp

# Opt — 논리 최적화
opt_design

# Place
place_design

# 배치 후 타이밍 분석
report_timing_summary -file ./reports/post_place_timing.rpt

# Phys Opt — 물리적 최적화 (배치 후, 배선 전)
phys_opt_design

# Route
route_design

# 배선 후 최종 타이밍
report_timing_summary -file ./reports/post_route_timing.rpt

# 체크포인트 저장
write_checkpoint -force ./checkpoint/post_impl.dcp
```

### 5.2 Implementation 단계별 설명

```
Synthesis netlist
       ↓
  [opt_design]        논리 최적화 — 중복 로직 제거, 상수 전파
       ↓
  [place_design]      FPGA 내 LUT/FF/BRAM/DSP 물리 위치 결정
       ↓
  [phys_opt_design]   배치 결과 기반 타이밍 최적화 — 크리티컬 패스 셀 재배치
       ↓
  [route_design]      물리 배선 연결
       ↓
  DRC + Timing Check
       ↓
  Bitstream 생성
```

### 5.3 Implementation 주요 옵션 (Strategy)

```tcl
# Implementation 전략 설정 (GUI: Implementation Settings)
set_property strategy Performance_ExplorePostRoutePhysOpt [get_runs impl_1]
```

**주요 Implementation 전략**

| 전략 | 설명 |
|---|---|
| `Vivado Implementation Defaults` | 기본 |
| `Performance_ExplorePostRoutePhysOpt` | 타이밍 성능 최대화, 시간 오래 걸림 |
| `Performance_NetDelay_low` | 배선 지연 최소화 |
| `Area_Explore` | 면적 최소화 |
| `Congestion_SpreadLogic_high` | 배선 혼잡도 분산 |
| `Flow_RuntimeOptimized` | 런타임 단축 (QoR 희생) |

### 5.4 Implementation 결과 확인

**타이밍 Closure 확인**
```tcl
# WNS > 0 이면 Timing Closed
report_timing_summary -no_header
```

**배선 혼잡도 확인**
```tcl
report_route_status -file route_status.rpt
```

```
Route Status Summary
---------------------
# of unrouted nets:        0     <- 반드시 0 이어야 함
# of fully routed nets: 8245
Routed:                 100.00%
```

**타이밍 닫히지 않을 때 대응 순서**

1. `phys_opt_design -directive AggressiveExplore` 추가 실행
2. XDC에서 `set_multicycle_path` 적용 가능한 경로가 있는지 검토
3. RTL에서 critical path에 파이프라인 레지스터 삽입
4. Pblock으로 관련 모듈들을 물리적으로 인접 배치
5. Implementation Strategy를 `Performance_ExplorePostRoutePhysOpt`로 변경

### 5.5 Device View 및 Schematic 분석

```tcl
# GUI에서 Device View 열기 — 실제 배치 확인
start_gui
open_run impl_1

# 특정 경로의 배치/배선 하이라이트
highlight_objects -color red [get_timing_paths -max_paths 1]
```

---

## 6. FPGA Bitstream

Bitstream은 FPGA 설정 정보를 담은 바이너리 파일(`.bit`)이다. Implementation이 완료된 후 생성하며, 이 파일을 FPGA에 다운로드하면 회로가 동작한다.

### 6.1 Bitstream 생성

**GUI**: `Flow Navigator` → `Program and Debug` → `Generate Bitstream`

**Tcl**:
```tcl
# Implementation 완료 상태에서 실행
write_bitstream -force ./output/top.bit

# 또는 비프로젝트 모드에서 체크포인트로부터
open_checkpoint ./checkpoint/post_impl.dcp
write_bitstream -force ./output/top.bit
```

**주요 옵션**
```tcl
write_bitstream \
    -force                        \  # 기존 파일 덮어쓰기
    -verbose                      \  # 상세 로그
    -bin_file                     \  # .bin 파일도 함께 생성 (SPI Flash용)
    ./output/top.bit
```

### 6.2 Bitstream 설정 옵션 (Bitstream Settings)

XDC 또는 Vivado 설정에서 Bitstream 생성 시 동작을 제어할 수 있다.

```xdc
# FPGA 설정 전압 명시 (DRC 경고 방지)
set_property CFGBVS         VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3  [current_design]

# 압축 Bitstream 생성 (SPI Flash 용량 절약)
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]

# SPI Flash 읽기 속도 설정
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4      [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE   33     [current_design]

# JTAG 및 사용자 코드
set_property BITSTREAM.CONFIG.USERID 0xABCD1234  [current_design]
```

Tcl로도 동일하게 설정 가능:
```tcl
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
write_bitstream -force ./output/top.bit
```

### 6.3 FPGA 프로그래밍 — JTAG (Hardware Manager)

**GUI 방법**

1. `Flow Navigator` → `Open Hardware Manager`
2. `Open Target` → `Auto Connect` (USB-JTAG 케이블 자동 인식)
3. 디바이스 우클릭 → `Program Device`
4. Bitstream 파일 선택 → `Program`

**Tcl 방법 (자동화)**
```tcl
open_hw_manager
connect_hw_server -url localhost:3121
open_hw_target

# 연결된 디바이스 확인
get_hw_devices

# 타겟 디바이스 선택 및 프로그래밍
set_property PROGRAM.FILE {./output/top.bit} [get_hw_devices xc7a35t_0]
program_hw_devices [get_hw_devices xc7a35t_0]

close_hw_target
disconnect_hw_server
```

### 6.4 SPI Flash 프로그래밍 (Non-volatile)

FPGA는 전원이 꺼지면 설정이 사라진다. 영구 저장을 위해 SPI Flash에 Bitstream을 기록한다.

```tcl
# MCS 파일 생성 (SPI Flash 포맷)
write_cfgmem \
    -format  mcs                   \
    -size    16                    \  # Flash 크기 (MB)
    -interface SPIx4               \  # Quad SPI
    -loadbit "up 0x0 ./output/top.bit" \
    -force   ./output/top.mcs

# Hardware Manager에서 Flash 프로그래밍
open_hw_manager
connect_hw_server
open_hw_target

set flash [get_hw_cfgmems -of_objects [get_hw_devices xc7a35t_0]]
set_property PROGRAM.FILES {./output/top.mcs} [get_hw_cfgmems $flash]
set_property PROGRAM.ERASE  1 [get_hw_cfgmems $flash]
set_property PROGRAM.BLANK_CHECK 1 [get_hw_cfgmems $flash]
set_property PROGRAM.VERIFY 1 [get_hw_cfgmems $flash]
program_hw_cfgmem [get_hw_cfgmems $flash]

boot_hw_device [get_hw_devices xc7a35t_0]
```

### 6.5 In-System Debug — ILA (Integrated Logic Analyzer)

ILA는 FPGA 내부 신호를 실시간으로 캡처하는 Vivado 내장 로직 분석기다. 오실로스코프처럼 동작하며, Bitstream에 내장된다.

**RTL에서 ILA 연결**
```verilog
// ILA IP를 인스턴스화
ila_0 u_ila (
    .clk    (clk_sys),
    .probe0 (wr_data),    // 8비트
    .probe1 (rd_data),    // 8비트
    .probe2 ({full, empty, wr_en, rd_en})  // 4비트
);
```

또는 `mark_debug` 속성으로 RTL에서 자동 삽입:
```verilog
(* mark_debug = "true" *) wire [7:0] wr_data;
(* mark_debug = "true" *) wire [7:0] rd_data;
(* mark_debug = "true" *) wire       full, empty;
```

Synthesis 후 `Set Up Debug` 위저드를 실행하면 Vivado가 자동으로 ILA를 삽입한다.

**ILA 사용 방법**
1. Bitstream을 FPGA에 다운로드
2. `Hardware Manager` → `hw_ila_1` 선택
3. Trigger 조건 설정 (예: `wr_en == 1`이 되는 시점 캡처)
4. `Run Trigger` → 조건 충족 시 내부 신호 파형 캡처

### 6.6 전체 설계 흐름 자동화 Tcl 스크립트

```tcl
#!/usr/bin/env tclsh
# run_flow.tcl — 비프로젝트 모드 전체 흐름

set TOP      "top"
set PART     "xc7a35tcpg236-1"
set SRC_DIR  "./src"
set OUT_DIR  "./output"
set RPT_DIR  "./reports"

file mkdir $OUT_DIR $RPT_DIR

# 1. 소스 읽기
read_verilog [glob $SRC_DIR/*.v]
read_xdc     ./constr/top.xdc

# 2. Synthesis
synth_design -top $TOP -part $PART -flatten_hierarchy rebuilt
write_checkpoint -force $OUT_DIR/post_synth.dcp
report_timing_summary -file $RPT_DIR/synth_timing.rpt
report_utilization    -file $RPT_DIR/synth_util.rpt

# 3. Implementation
opt_design
place_design
phys_opt_design
route_design
write_checkpoint -force $OUT_DIR/post_impl.dcp

# 4. 레포트
report_timing_summary    -file $RPT_DIR/impl_timing.rpt
report_utilization       -file $RPT_DIR/impl_util.rpt
report_power             -file $RPT_DIR/impl_power.rpt
report_drc               -file $RPT_DIR/impl_drc.rpt
report_clock_interaction -file $RPT_DIR/impl_clock.rpt

# 5. Timing 체크 — 위반 시 에러
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
if {$wns < 0} {
    puts "ERROR: Timing not closed. WNS = $wns ns"
    exit 1
}
puts "Timing closed. WNS = $wns ns"

# 6. Bitstream 생성
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
write_bitstream -force $OUT_DIR/top.bit
puts "Bitstream generated: $OUT_DIR/top.bit"
```

실행:
```bash
vivado -mode batch -source run_flow.tcl -log run.log
```

---

## 요약 표

| 단계 | 주요 Tcl 명령어 | 핵심 확인 항목 |
|---|---|---|
| RTL 작성 | `read_verilog`, `add_files` | 언어 표준, 파라미터화, IP 설정 |
| XDC 작성 | `create_clock`, `set_false_path` | 모든 클럭 정의, CDC false path, 핀 배정 |
| Synthesis | `synth_design`, `launch_runs synth_1` | Latch 경고, 자원 사용량, 타이밍 estimate |
| Implementation | `place_design`, `route_design` | WNS > 0, unrouted nets = 0 |
| 레포트 | `report_timing_summary`, `report_drc` | Timing/DRC/Clock Interaction |
| Bitstream | `write_bitstream`, `program_hw_devices` | Bitstream 설정, Flash 프로그래밍 |

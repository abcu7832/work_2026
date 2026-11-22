# Darkroom: ISP Line Buffer Architecture 기술 분석

> **논문:**
> 
> 
> **저자:**
> 
> **학회:**
> 
> **분야:**
> 
> **DOI:**
> 
> **원문:**
> 
> [https://graphics.stanford.edu/papers/darkroom14/darkroom14-low.pdf](https://graphics.stanford.edu/papers/darkroom14/darkroom14-low.pdf)
> 

---

## 1. 연구 개요

### 1.1 연구 배경

이미지 신호 처리기(ISP, Image Signal Processor)는 카메라 센서에서 입력받은 RAW 데이터를 다양한 영상 처리 단계를 거쳐 최종 이미지로 변환하는 전용 프로세서다.

일반적인 ISP는 다음과 같은 처리 단계를 포함한다.

1. RAW Input
2. Black Level Correction
3. Dead Pixel Correction
4. Crosstalk Correction
5. Demosaicing
6. White Balance
7. Color Correction
8. Gamma Correction
9. Image Output

각 처리 단계는 이전 단계의 출력 데이터를 입력으로 사용한다.

이때 중요한 문제는 중간 처리 결과를 어떻게 저장하고 다음 단계에 전달할 것인가이다.

일반적인 CPU/GPU 방식에서는 중간 이미지 데이터를 DRAM에 저장하고 다시 읽는 과정이 발생할 수 있다.

그러나 모바일 카메라와 같은 임베디드 환경에서는 다음 요소가 중요하다.

- 메모리 대역폭
- 메모리 접근 전력
- 칩 면적
- 처리 지연 시간
- 실시간 처리 성능

따라서 ISP는 중간 데이터를 외부 DRAM에 반복적으로 저장하는 대신, 칩 내부 SRAM에 임시 저장하는 Line Buffer 구조를 활용한다.

### 1.2 Darkroom의 연구 목적

Darkroom은 이미지 처리 알고리즘을 고수준 언어로 기술하면 이를 자동으로 Line-buffered Pipeline으로 변환하는 언어 및 컴파일러다.

주요 목적은 다음과 같다.

- 이미지 처리 알고리즘의 하드웨어 구현 자동화
- 중간 데이터의 외부 DRAM 접근 최소화
- Line Buffer 메모리 사용량 최적화
- ASIC 및 FPGA 하드웨어 자동 생성
- CPU용 최적화 코드 생성

기존에는 ISP의 각 단계를 하드웨어 설계자가 직접 분석하고 버퍼 크기 및 처리 타이밍을 설계해야 했다.

Darkroom은 이러한 작업을 컴파일러가 자동으로 수행하도록 한다.

---

## 2. ISP에서 Line Buffer가 필요한 이유

### 2.1 이미지 처리의 데이터 접근 특성

이미지 데이터는 일반적으로 Raster Scan 방식으로 처리된다.

Raster Scan은 다음과 같은 순서로 픽셀을 읽는 방식이다.

text

```
Pixel 0  -> Pixel 1  -> Pixel 2  -> ... -> Pixel W-1
Pixel W  -> Pixel W+1 -> Pixel W+2 -> ...
Pixel 2W -> Pixel 2W+1 -> ...
```

즉, 한 라인을 왼쪽에서 오른쪽으로 처리한 다음 다음 라인으로 이동한다.

하지만 많은 이미지 처리 알고리즘은 현재 픽셀 하나만으로 결과를 계산하지 않는다.

예를 들어 3×3 Gaussian Filter는 현재 픽셀 주변의 9개 픽셀을 사용한다.

text

```
P(x-1,y-1)  P(x,y-1)  P(x+1,y-1)
P(x-1,y)    P(x,y)    P(x+1,y)
P(x-1,y+1)  P(x,y+1)  P(x+1,y+1)
```

이때 현재 픽셀을 처리하려면 이전 라인에서 입력받았던 픽셀도 다시 사용할 수 있어야 한다.

외부 메모리에서 매번 해당 픽셀을 가져오는 것은 대역폭과 전력 측면에서 비효율적이다.

따라서 이전에 입력받은 픽셀을 칩 내부에 저장하는 Line Buffer가 필요하다.

### 2.2 Line Buffer의 기본 개념

Line Buffer는 이미지 처리에 필요한 이전 라인의 데이터를 SRAM 등에 임시 저장하는 메모리 구조다.

3×3 윈도우를 사용하는 경우 일반적으로 이전 2개 라인의 픽셀 데이터를 보관하고, 현재 입력 라인의 픽셀과 함께 3×3 윈도우를 구성한다.

text

```
          Input Pixel Stream
                  |
                  v
          +---------------+
          | Current Line  |
          +---------------+
                  |
                  v
          +---------------+
          | Line Buffer 1 |
          +---------------+
                  |
                  v
          +---------------+
          | Line Buffer 2 |
          +---------------+
                  |
                  v
          +---------------+
          | 3x3 Window    |
          | Shift Register|
          +---------------+
                  |
                  v
          +---------------+
          | Image Filter  |
          +---------------+
                  |
                  v
              Output
```

개념적으로 3개 라인의 데이터를 이용하지만, 이전 라인 2개를 저장하는 Line Buffer와 현재 입력 라인을 조합하는 방식으로 구현할 수 있다.

### 2.3 Line Buffer의 메모리 크기

이미지 너비를 W, 픽셀당 데이터 크기를 B bytes, 필요한 수직 윈도우 크기를 K라고 정의하면 일반적인 Line Buffer의 저장 용량은 다음과 같이 계산할 수 있다.

text

```
Line Buffer Size = (K - 1) × W × B
```

예를 들어 다음 조건을 가정한다.

- Image Width: 1920 pixels
- Pixel Data Width: 16 bits
- Kernel Size: 3×3

필요한 Line Buffer 크기는 다음과 같다.

text

```
Line Buffer Size
= (3 - 1) × 1920 × 2
= 7680 bytes
= 7.5 KB
```

이는 단일 데이터 스트림을 대상으로 한 기본적인 계산이다.

실제 ISP에서는 다음 요소에 따라 메모리 크기가 달라진다.

- Pixel bit depth
- Processing stage 개수
- 각 Stage의 Window 크기
- 중간 데이터의 bit width
- 데이터 재사용 구조
- 여러 Consumer의 존재 여부

---

## 3. ISP 처리 연산의 두 가지 유형

Darkroom은 이미지 처리 연산을 크게 Pointwise Operation과 Stencil Operation으로 구분한다.

이 구분은 Line Buffer의 필요 여부를 판단하는 핵심 요소다.

### 3.1 Pointwise Operation

Pointwise Operation은 현재 위치의 픽셀 하나만 사용해 출력 픽셀을 계산하는 연산이다.

예를 들어 Gamma Correction은 현재 픽셀의 입력값을 변환해 출력한다.

text

```
Output(x,y) = Gamma(Input(x,y))
```

이전 라인의 데이터를 참조할 필요가 없다.

따라서 별도의 Line Buffer가 필요하지 않다.

대표적인 연산은 다음과 같다.

- Gamma Correction
- 일부 Color Correction 연산
- Pixel-wise Scaling
- 단순 LUT 기반 변환

### 3.2 Stencil Operation

Stencil Operation은 현재 픽셀 주변의 일정한 크기의 Window를 사용하여 결과를 계산한다.

예를 들어 3×3 Gaussian Filter는 다음과 같이 표현할 수 있다.

text

```
Output(x,y) =

    Sum(
        Input(x+i, y+j) × Weight(i,j)
    )
```

여기서 i와 j는 -1부터 1까지의 범위를 가진다.

이 연산은 현재 픽셀뿐 아니라 이전 및 다음 라인의 픽셀까지 필요하다.

따라서 Line Buffer를 사용해야 한다.

대표적인 연산은 다음과 같다.

- Demosaicing
- Gaussian Filter
- Median Filter
- Edge Detection
- Image Sharpening
- Denoising
- Deblurring

### 3.3 Pointwise와 Stencil 비교

| 항목 | Pointwise | Stencil |
| --- | --- | --- |
| 입력 데이터 | 단일 픽셀 | 주변 픽셀 Window |
| Line Buffer | 불필요 | 일반적으로 필요 |
| Shift Register | 불필요할 수 있음 | 필요 |
| 데이터 재사용 | 제한적 | 높음 |
| 구현 복잡도 | 낮음 | 상대적으로 높음 |

핵심은 모든 ISP 단계가 Line Buffer를 필요로 하는 것은 아니라는 점이다.

Stencil을 사용하는 단계에서 필요한 데이터만 버퍼링하는 것이 효율적인 ISP 구조를 만드는 데 중요하다.

---

## 4. Darkroom의 Line-buffered Pipeline

### 4.1 기본 구조

Darkroom은 각 이미지 처리 단계를 함수 형태로 표현한다.

각 단계는 입력 이미지 또는 이전 단계의 출력 이미지에 대한 연산으로 정의된다.

이를 Directed Acyclic Graph(DAG) 형태로 구성한다.

text

```
Input Image
     |
     v
  Stage A
     |
     v
  Line Buffer
     |
     v
  Stage B
     |
     v
  Line Buffer
     |
     v
  Stage C
     |
     v
  Output Image
```

각 Stage는 입력 데이터를 처리하면서 다음 Stage가 필요한 데이터를 생성한다.

중요한 점은 전체 이미지가 완성될 때까지 기다릴 필요가 없다는 것이다.

필요한 Window 데이터가 준비되면 다음 Stage는 즉시 처리를 시작할 수 있다.

즉, 이미지 전체 단위가 아닌 Pixel 단위의 Streaming Pipeline을 구성한다.

### 4.2 Shift Register와 Line Buffer

Darkroom에서 중요한 개념 중 하나는 Line Buffer와 Shift Register의 역할이 다르다는 것이다.

**Line Buffer**

- 이전 라인의 픽셀 데이터를 저장한다.
- 일반적으로 SRAM 기반으로 구현한다.
- 현재 처리 위치에서 필요한 이전 라인의 데이터를 제공한다.

**Shift Register**

- 현재 연산에 필요한 인접 픽셀들을 보관한다.
- Window가 이동할 때 새로운 픽셀을 입력받는다.
- 기존 데이터를 이동시켜 다음 Window를 구성한다.

예를 들어 3×3 Window는 다음과 같이 구성된다.

text

```
+-----+-----+-----+
| P00 | P01 | P02 |
+-----+-----+-----+
| P10 | P11 | P12 |
+-----+-----+-----+
| P20 | P21 | P22 |
+-----+-----+-----+
```

한 픽셀 오른쪽으로 이동하면 이전 Window의 일부 데이터를 재사용한다.

text

```
+-----+-----+-----+
| P01 | P02 | P03 |
+-----+-----+-----+
| P11 | P12 | P13 |
+-----+-----+-----+
| P21 | P22 | P23 |
+-----+-----+-----+
```

이러한 구조를 이용하면 매번 9개의 픽셀을 외부에서 읽을 필요가 없다.

이전 Window에서 6개의 픽셀을 재사용하고 새로운 Column만 추가하면 된다.

### 4.3 2D Image를 1D Stream으로 처리

Darkroom은 2D 이미지의 접근 패턴을 1D 연속 데이터 스트림으로 변환해 처리한다.

이미지는 다음과 같은 순서로 입력된다.

text

```
Row 0: P00 P01 P02 P03 ...
Row 1: P10 P11 P12 P13 ...
Row 2: P20 P21 P22 P23 ...
```

시간 순서에 따라 입력된 픽셀은 Line Buffer에 저장된다.

예를 들어 3×3 Window를 사용하는 경우 현재 픽셀을 처리하기 위해 이전 2개 라인의 픽셀을 보관한다.

이미지 너비가 W일 때 이전 라인의 동일한 X 좌표 픽셀은 약 W Clock Cycle 전에 입력된 데이터다.

따라서 Line Buffer를 통해 해당 데이터를 다시 가져올 수 있다.

이 방식은 2D 이미지 연산을 Streaming Hardware Pipeline으로 구현할 수 있게 한다.

---

## 5. Darkroom의 핵심 기술: Buffer Size Optimization

### 5.1 왜 Buffer Optimization이 필요한가?

단순히 모든 중간 데이터를 저장한다면 ISP의 SRAM 사용량은 매우 커질 수 있다.

하지만 실제로 각 처리 단계가 필요로 하는 데이터는 제한적이다.

예를 들어 다음과 같은 파이프라인을 생각할 수 있다.

text

```
Input
  |
  v
Stage A
  |
  v
Stage B
  |
  v
Stage C
  |
  v
Output
```

Stage B가 3×3 Window를 필요로 한다면 Stage A의 결과 중 필요한 이전 라인 데이터만 보관하면 된다.

모든 중간 데이터를 전체 이미지 크기로 저장할 필요가 없다.

Darkroom은 이러한 데이터 의존성과 처리 순서를 분석해 필요한 최소 Buffer 크기를 계산한다.

### 5.2 Scheduling Optimization

Darkroom은 Line Buffer의 크기를 최소화하기 위해 Integer Linear Programming(ILP)을 사용한다.

ILP는 정수 변수와 선형 제약 조건을 이용하여 최적화 문제를 해결하는 수학적 기법이다.

Darkroom에서는 각 처리 단계의 실행 순서와 데이터 소비 시점을 고려한다.

최적화 목표는 다음과 같다.

text

```
Minimize:

Total Line Buffer Size
```

단, 다음 조건을 만족해야 한다.

- 모든 데이터 의존성이 충족되어야 한다.
- 각 Stage가 필요한 입력 데이터를 제공받아야 한다.
- Stencil Window를 구성할 수 있어야 한다.
- Pipeline의 처리 순서가 유지되어야 한다.

이를 통해 각 Stage 사이에 필요한 Buffer 크기를 계산한다.

### 5.3 Buffer Size와 Pipeline Scheduling의 관계

Buffer가 너무 작으면 다음 Stage가 필요한 데이터를 읽기 전에 이전 데이터가 덮어써질 수 있다.

반대로 Buffer가 너무 크면 불필요한 SRAM 면적과 전력이 증가한다.

따라서 Buffer 크기는 데이터 생산 시점과 소비 시점에 따라 결정되어야 한다.

text

```
Producer Stage
      |
      v
 Intermediate Data
      |
      v
   Line Buffer
      |
      v
 Consumer Stage
```

Darkroom은 이러한 Producer-Consumer 관계를 분석하여 최소한의 Buffer 사용량으로 Pipeline을 구성한다.

---

## 6. Darkroom Compiler Architecture

Darkroom은 고수준 이미지 처리 코드를 실제 하드웨어 구조로 변환하는 컴파일러다.

전체적인 처리 과정은 다음과 같다.

text

```
Image Processing Algorithm
            |
            v
      Darkroom DSL
            |
            v
       Functional DAG
            |
            v
  Line Buffer Scheduling
            |
            v
    Buffer Optimization
            |
            v
    Pipeline Generation
            |
      +-----+-----+
      |     |     |
      v     v     v
     ASIC  FPGA  CPU
```

### 6.1 DSL (Domain Specific Language)

Darkroom은 이미지 처리에 특화된 언어를 제공한다.

일반적인 프로그래밍 언어와 달리 이미지 좌표와 주변 Window를 중심으로 알고리즘을 기술한다.

예를 들어 다음과 같은 개념이다.

text

```
Output(x,y) = Input(x,y)
```

Stencil 기반 연산은 주변 픽셀을 참조하는 함수 형태로 표현한다.

### 6.2 Functional DAG

각 처리 단계를 함수 노드로 표현하고 데이터 의존성을 DAG로 구성한다.

예를 들어 다음과 같다.

text

```
          Input
            |
      +-----+-----+
      |           |
      v           v
   Demosaic   Correction
      |           |
      v           v
   Denoising  Sharpening
      |           |
      +-----+-----+
            |
            v
          Output
```

이러한 데이터 의존성을 분석하면 각 단계 사이에 어떤 데이터가 얼마나 오래 유지되어야 하는지 계산할 수 있다.

### 6.3 Hardware Generation

Darkroom은 최적화된 Pipeline을 기반으로 여러 플랫폼에 대한 구현을 생성한다.

- ASIC: Structural Verilog 기반 하드웨어 생성
- FPGA: 하드웨어 합성 가능한 구조 생성
- CPU: 최적화된 소프트웨어 코드 생성

즉, 동일한 이미지 처리 알고리즘을 여러 하드웨어 플랫폼에서 실행할 수 있도록 한다.

---

## 7. 논문의 실험 결과

Darkroom은 Camera Pipeline, Edge Detection, Corner Detection, Deblurring 등의 알고리즘을 대상으로 실험을 수행했다.

논문에서 제시한 주요 성능 결과는 다음과 같다.

| 항목 | 논문 결과 |
| --- | --- |
| ASIC 공정 | 45nm 시뮬레이션 |
| ASIC 면적 | 일부 구현에서 0.5mm² 미만 |
| ASIC 전력 | 일부 구현에서 약 250mW |
| FPGA 처리 성능 | 약 125~145 MPixel/s |
| 영상 처리 | 1080p 60fps 실시간 처리 |
| CPU 처리 | Quad-core x86에서 수십 MPixel/s |
| Buffer 최적화 | 실제 구현에서 최적 Buffer의 3배 미만 사용 |

위 결과는 논문에서 평가한 특정 알고리즘 및 구현 환경에 대한 결과다.

모든 ISP 설계에서 동일한 성능을 보장하는 수치는 아니다.

### 7.1 주요 성과

Darkroom의 가장 큰 성과는 이미지 처리 알고리즘을 하드웨어로 변환하는 과정에서 Line Buffer의 크기와 Pipeline Scheduling을 자동으로 최적화했다는 점이다.

기존의 수작업 중심 하드웨어 설계에서 발생하던 복잡성을 줄이고, 효율적인 ISP 구조를 자동으로 생성할 수 있음을 보여주었다.

---

## 8. Darkroom의 한계와 후속 연구

Darkroom은 중요한 연구이지만 모든 ISP의 메모리 구조를 해결하는 범용 솔루션은 아니다.

특히 다음과 같은 제약이 있다.

- 제한된 형태의 이미지 연산을 대상으로 한다.
- 고정 크기의 Stencil 기반 연산을 중심으로 한다.
- 기존 연구에서 Single Consumer 구조를 가정한다.
- 특정 메모리 포트 구조에 의존한다.

실제 ISP에서는 하나의 처리 결과를 여러 단계에서 동시에 사용하는 경우가 있다.

예를 들어 Denoising과 Sharpening이 동일한 중간 데이터를 참조할 수 있다.

이때 여러 Consumer가 같은 Line Buffer에 접근하면서 SRAM Port Contention이 발생할 수 있다.

### 8.1 후속 연구: ImaGen (ISCA 2023)

관련 후속 연구로 다음 논문이 있다.

**ImaGen: A General Framework for Generating Memory- and Power-Efficient Image Processing Accelerators**

저자: Nisarg Ujjainkar, Jingwen Leng, Yuhao Zhu

ImaGen은 Darkroom과 같은 기존 이미지 처리 가속기의 메모리 구조상 제약을 개선하려는 연구다.

Darkroom과 비교하면 다음과 같은 차이가 있다.

| 항목 | Darkroom | ImaGen |
| --- | --- | --- |
| 발표 | SIGGRAPH 2014 | ISCA 2023 |
| 기본 목적 | ISP Pipeline 자동 생성 | 메모리 및 전력 최적화 |
| 알고리즘 | 제한된 Consumer 구조 | Generic 알고리즘 지원 |
| 메모리 구조 | Dual-port 기반 가정 | 다양한 메모리 구조 지원 |
| 최적화 | ILP 기반 Buffer Scheduling | 제약 최적화 및 메모리 설계 탐색 |
| 주요 특징 | 최소 Buffer 구성 | 다중 Consumer 및 메모리 경합 고려 |

ImaGen은 Line Buffer의 여러 라인을 하나의 메모리 블록으로 통합하는 Line Coalescing 기법도 제안한다.

논문에서는 기존 방식과 비교해 특정 실험에서 On-chip Memory 사용량을 최대 86.0%, 전력 소비를 최대 62.9% 줄였다고 보고한다.

이는 해당 연구의 평가 환경에서 얻은 결과다.

---

## 9. 실제 ISP 설계 관점에서의 핵심 정리

Darkroom 논문을 실제 ISP 하드웨어 설계 관점에서 해석하면 다음과 같은 의미가 있다.

### 9.1 Line Buffer는 단순한 FIFO가 아니다

Line Buffer는 이전에 입력된 픽셀을 저장하는 메모리이면서 동시에 여러 처리 단계의 데이터 의존성을 유지하는 구조다.

따라서 다음 요소를 함께 고려해야 한다.

- 데이터 입력 순서
- 데이터 소비 시점
- Window 크기
- Pixel Width
- SRAM Port 개수
- Read/Write 동시성
- 데이터 재사용 범위

### 9.2 SRAM과 Shift Register의 역할 분리

효율적인 ISP 구조에서는 큰 데이터 저장을 SRAM 기반 Line Buffer가 담당하고, 현재 연산에 필요한 작은 Window는 Shift Register가 담당한다.

이러한 구조는 메모리 면적과 접근 효율을 동시에 고려한 설계 방식이다.

### 9.3 Processing Stage별 Buffer 크기 최적화

모든 Stage가 동일한 Buffer 크기를 필요로 하는 것은 아니다.

예를 들어 Pointwise 연산은 별도의 Line Buffer가 필요하지 않을 수 있지만, 5×5 Stencil 연산은 더 많은 이전 라인 데이터를 요구한다.

따라서 Stage별 Window 크기와 데이터 의존성을 분석해 Buffer를 할당해야 한다.

### 9.4 Multi-Consumer 구조의 중요성

실제 ISP에서는 하나의 중간 데이터를 여러 처리 단계가 공유할 수 있다.

이 경우 단순히 Buffer 크기만 계산해서는 충분하지 않다.

다음 항목을 함께 고려해야 한다.

- 동시에 발생하는 SRAM Read 요청
- Write와 Read의 충돌
- SRAM Port 개수
- Arbitration
- Pipeline Stall
- 데이터 복제 여부

이 문제는 Darkroom 이후의 ImaGen 연구에서 중요하게 다루는 주제다.

---

## 10. 핵심 요약

Darkroom 논문의 핵심은 다음과 같이 정리할 수 있다.

1. ISP는 높은 전력 효율과 메모리 대역폭 효율을 위해 Line Buffer 기반 Pipeline을 사용한다.
2. 이미지 처리 연산은 Pointwise와 Stencil로 구분할 수 있다.
3. Stencil 연산은 이전 라인의 데이터를 필요로 하므로 Line Buffer가 중요하다.
4. Line Buffer는 이전 라인의 데이터를 저장하고 Shift Register는 현재 Window를 구성한다.
5. Darkroom은 이미지 처리 알고리즘을 DAG로 표현하고 Line-buffered Pipeline으로 자동 변환한다.
6. ILP를 활용해 필요한 Buffer 크기를 최소화한다.
7. 동일한 알고리즘을 ASIC, FPGA, CPU용으로 생성할 수 있다.
8. 다중 Consumer 및 SRAM Port Contention 문제는 후속 연구에서 중요한 개선 대상이다.

**가장 중요한 설계 관점은 Line Buffer의 크기를 단순히 Window 크기만으로 결정하는 것이 아니라, 각 Processing Stage의 데이터 생산 시점과 소비 시점, 그리고 데이터 의존성을 함께 분석해야 한다는 것이다.**

---

## 11. 참고 문헌 및 추가 자료

### 원본 논문

- Hegarty et al., Darkroom: Compiling High-Level Image Processing Code into Hardware Pipelines, SIGGRAPH 2014.
- DOI: https://doi.org/10.1145/2601097.2601174
- PDF: [https://graphics.stanford.edu/papers/darkroom14/darkroom14-low.pdf](https://graphics.stanford.edu/papers/darkroom14/darkroom14-low.pdf)

### 후속 연구

- Ujjainkar et al., ImaGen: A General Framework for Generating Memory- and Power-Efficient Image Processing Accelerators, ISCA 2023.
- PDF: [https://cs.sjtu.edu.cn/~leng-jw/resources/Files/ujjainkar2023isca-imagen.pdf](https://cs.sjtu.edu.cn/~leng-jw/resources/Files/ujjainkar2023isca-imagen.pdf)
- GitHub: https://github.com/horizon-research/imagen

### 관련 연구

- High-Throughput Line Buffer Microarchitecture for Arbitrary Sized Streaming Image Processing.
- [https://pmc.ncbi.nlm.nih.gov/articles/PMC8320917/](https://pmc.ncbi.nlm.nih.gov/articles/PMC8320917/)
- Virtual Linebuffers for Image Signal Processors.
- [https://data.epo.org/publication-server/rest/v1.2/patents/EP3667607NWB1/document.html](https://data.epo.org/publication-server/rest/v1.2/patents/EP3667607NWB1/document.html)

---

## 12. 결론

Darkroom은 ISP의 전통적인 Line Buffer 구조를 컴파일러 관점에서 분석하고 자동화한 대표적인 연구다.

특히 Line Buffer의 크기와 Pipeline Scheduling을 함께 최적화한다는 점에서 ISP의 메모리 아키텍처를 이해하는 데 중요한 자료다.

실제 하드웨어를 설계할 때는 Darkroom의 기본 구조를 이해한 다음, 다중 Consumer, SRAM Port 제한, Buffer 공유 및 데이터 재사용 문제까지 확장해서 검토하는 것이 바람직하다.
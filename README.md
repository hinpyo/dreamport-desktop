# Apple Health → OSCAR Desktop

Apple Health의 수면 데이터(`export.xml` / `export.zip`)를 OSCAR가 import할 수 있는 Dreem / ZEO CSV로 변환하는 데스크톱 앱입니다.

이번 구조 정리는 **기존 변환 엔진의 출력 포맷, manifest 처리, 증분 재실행 규칙을 유지**하면서 다음 영역을 안전하게 리팩터링하는 데 집중했습니다.

- Tkinter GUI 재구성
- 옵션 metadata / 툴팁 / 설정 창
- IANA timezone 카탈로그
- 다국어 리소스 구조
- macOS / Windows 아이콘 파이프라인
- PyInstaller 패키징 경로 안정화

## 유지한 핵심 원칙

1. **Dreem / ZEO 변환 결과 포맷 유지**
2. **manifest 기반 증분 처리 유지**
3. **기존 CLI / GUI 엔트리포인트 유지**
4. **기존 기본 옵션값 유지**
5. **엔진 로직보다 UI / 설정 / 리소스 계층 우선 개선**

## 프로젝트 구조

```text
.
├─ dreamport.py                     # DreamPort CLI 진입점
├─ dreamport_gui.py                 # DreamPort GUI 진입점
├─ oscar.py                         # 레거시 CLI 호환 진입점
├─ oscar_gui.py                     # 레거시 GUI 호환 진입점
├─ assets/
│  ├─ oscar_icon.png                # 원본 PNG 아이콘 소스
│  ├─ oscar_icon_runtime.png        # 런타임 / Windows용 파생 PNG
│  ├─ oscar_icon_macos.png          # macOS preview / source-run PNG
│  ├─ oscar_icon.ico                # Windows 패키징 아이콘
│  ├─ oscar_icon.icns               # macOS 패키징 아이콘
│  └─ macos.iconset/                # macOS iconset 파생 자산
├─ scripts/
│  ├─ prepare_icons.py              # PNG source -> macOS / Windows 자산 생성
│  ├─ build_app.py                  # PyInstaller 빌드 스크립트
│  └─ archive_dist.py               # 배포 zip 생성
├─ src/apple_health_to_oscar/
│  ├─ engine.py                     # 핵심 변환 엔진
│  ├─ cli.py                        # CLI
│  ├─ gui.py                        # Tkinter GUI
│  ├─ app_paths.py                  # 개발/배포 공용 경로 처리
│  ├─ settings_store.py             # 사용자 설정 저장
│  ├─ options.py                    # 옵션 metadata
│  ├─ i18n.py                       # 다국어 로더
│  ├─ timezones.py                  # timezone 카탈로그 로더
│  └─ resources/
│     ├─ timezones.json             # 사용자 친화적 timezone 데이터
│     └─ locales/*.json             # 언어 리소스
└─ tests/
   ├─ fixtures/sample_export.xml
   └─ test_engine_regression.py
```

## 실행 방법

### CLI

```bash
python dreamport.py --input /path/to/export.zip --output-dir /path/to/output
```

### GUI

```bash
python dreamport_gui.py
```

메인 화면에는 핵심 흐름만 남겨 두었습니다.

- 입력 파일 선택
- 출력 폴더 선택
- 출력 형식 선택
- 타임존 선택
- 변환 실행

상세 옵션은 **Preferences** 창으로 이동했습니다.

## 다국어 지원

현재 UI 리소스 구조는 다음 언어를 지원합니다.

- 한국어 (`ko`)
- 영어 (`en`)
- 일본어 (`ja`)
- 독일어 (`de`)
- 프랑스어 (`fr`)
- 이탈리아어 (`it`)
- 스페인어 (`es`)
- 포르투갈어 (`pt`)
- 힌디어 (`hi`)
- 러시아어 (`ru`)
- 중국어 간체 (`zh-Hans`)
- 중국어 번체 (`zh-Hant`)
- 인도네시아어 (`id`)

아랍어(`ar`)는 이번 턴에서는 제외했습니다. Tkinter의 RTL 레이아웃 미러링을 안전하게 마무리하지 않은 상태에서 억지로 켜는 것보다, 현재 데스크톱 UX를 안정적으로 유지하는 편이 더 안전하다고 판단했습니다.

## 아이콘 파이프라인

원본 소스는 `assets/oscar_icon.png` 입니다.

```bash
python scripts/prepare_icons.py
```

이 스크립트는 다음 흐름으로 자산을 생성합니다.

- 원본 PNG에서 연결된 흰색 배경을 분리해 실제 일러스트를 추출
- macOS용 safe-area 반영 master PNG 생성
- Windows / runtime용 PNG 생성
- `oscar_icon.ico` 생성
- `oscar_icon.icns` 생성
- `macos.iconset/` 크기별 PNG 생성

### macOS iconset 크기

- 16
- 32
- 64
- 128
- 256
- 512
- 1024

각 크기는 iconset naming 규칙에 맞춰 `@2x` 쌍으로 함께 생성됩니다.

## 패키징

```bash
python -m pip install -r requirements.txt
python scripts/prepare_icons.py
python scripts/build_app.py
```

기본 전략:

- macOS: `.app` 번들 (`onedir`)
- Windows: 단일 `.exe` (`onefile`)

리소스는 다음 두 경로로 번들에 포함됩니다.

- `assets/`
- `apple_health_to_oscar/resources/`

## macOS 아이콘 관련 구현 메모

현재 Dock에서 곡률이 어색하게 보였던 주된 이유는 두 가지였습니다.

1. **원본 PNG가 이미 흰색 squircle 배경을 포함하고 있었음**
2. **macOS 패키징 아이콘(`.icns`)과 런타임 `iconphoto()` 적용이 서로 겹칠 수 있었음**

이번 수정에서는:

- 원본 PNG를 macOS용 배경 일러스트와 분리해 새 master를 생성하고
- 패키징된 macOS 앱에서는 Tk `iconphoto()`로 Dock 아이콘을 덮어쓰지 않으며
- `.icns`를 번들 아이콘의 우선 경로로 사용합니다.

## 테스트

```bash
python -m unittest discover -s tests
```

현재 회귀 테스트는 다음을 검증합니다.

- 기존 엔진이 Dreem / ZEO 파일을 정상 생성하는지
- 두 번째 실행에서 manifest 기반 재사용이 유지되는지
- timezone 카탈로그가 넓은 오프셋 범위를 포함하는지

## 주의사항

### macOS

- 서명/노타라이즈가 없는 로컬 빌드는 Gatekeeper 경고가 날 수 있습니다.
- 패키징된 앱은 `.icns` 번들 아이콘을 사용하고, 소스 실행 모드만 PNG 런타임 아이콘을 사용합니다.

### Windows

- 서명되지 않은 `.exe`는 SmartScreen 경고가 날 수 있습니다.
- 기본 배포 전략은 단일 `.exe` 이며, 아이콘 / 번역 / timezone 리소스는 PyInstaller 데이터로 함께 포함됩니다.

## 개발 메모

- 변환 엔진은 의도적으로 보수적으로 유지했습니다.
- 다국어 / timezone / 옵션 metadata / 설정 저장은 UI 계층에 분리했습니다.
- 향후 iOS / SwiftUI 프런트엔드로 확장할 때도 재사용할 수 있도록 리소스 파일과 schema를 패키지 내부에 모았습니다.

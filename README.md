# Apple Health → OSCAR Desktop

Apple Health의 수면 데이터(`export.xml` / `export.zip`)를 OSCAR가 import할 수 있는 Dreem / ZEO CSV로 변환하는 데스크톱 앱입니다.

## 유지한 핵심 원칙

1. **Dreem / ZEO 변환 결과 포맷 유지**
2. **manifest 기반 증분 처리 유지**
3. **기존 기본 옵션값 유지**
4. **엔진 로직보다 UI / 설정 / 리소스 계층 우선 개선**

## 프로젝트 구조

```text
.
├─ dreamport_gui.py                 # DreamPort GUI 진입점
├─ assets/
│  ├─ oscar_icon.png                # 원본 PNG 아이콘 소스
│  ├─ oscar_icon_runtime.png        # 런타임 / Windows용 파생 PNG
│  ├─ oscar_icon_macos.png          # macOS preview / source-run PNG
│  ├─ oscar_icon.ico                # Windows 패키징 아이콘
│  ├─ oscar_icon.icns               # macOS 패키징 아이콘
│  ├─ settings.png                  # 설정 진입 아이콘
│  └─ macos.iconset/                # macOS iconset 파생 자산
├─ scripts/
│  ├─ prepare_icons.py              # PNG source -> macOS / Windows 자산 생성
│  ├─ build_app.py                  # PyInstaller 빌드 스크립트
│  └─ archive_dist.py               # 배포 zip 생성
├─ src/apple_health_to_oscar/
│  ├─ engine.py                     # 핵심 변환 엔진
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
   ├─ test_engine_regression.py
   └─ test_i18n_and_timezones.py
```

## 실행 방법

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

| 코드 | 언어 |
|------|------|
| `en` | English |
| `en-GB` | English (UK) |
| `ko` | 한국어 |
| `ja` | 日本語 |
| `de` | Deutsch |
| `fr` | Français |
| `it` | Italiano |
| `es` | Español |
| `es-MX` | Español (México) |
| `pt` | Português |
| `pt-BR` | Português (Brasil) |
| `hi` | हिन्दी |
| `ru` | Русский |
| `uk` | Українська |
| `zh-Hans` | 简体中文 |
| `zh-Hant` | 繁體中文 |
| `id` | Bahasa Indonesia |
| `ms` | Bahasa Melayu |
| `af` | Afrikaans |
| `ar` | العربية |
| `bg` | Български |
| `el` | Ελληνικά |
| `he` | עברית |
| `nl` | Nederlands |
| `nb` | Norsk Bokmål |
| `pl` | Polski |
| `ro` | Română |
| `fi` | Suomi |
| `sv` | Svenska |
| `tr` | Türkçe |
| `th` | ไทย |
| `vi` | Tiếng Việt |
| `da` | Dansk |
| `cs` | Čeština |

## 아이콘 파이프라인

원본 소스는 `assets/oscar_icon.png` 입니다.

```bash
python scripts/prepare_icons.py
```

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

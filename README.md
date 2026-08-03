# Gesture Remote

Apple Watch Series 7의 손목 움직임과 AssistiveTouch, Digital Crown을 이용해
Windows의 화면 넘김, 스크롤, 확대·축소, 볼륨과 미디어 재생을 제어하는 초기 버전입니다.

## 구성

- `windows`: Windows 10/11용 .NET 8 수신기
- `apple/MacApp`: macOS 메뉴 막대 수신 앱
- `apple/iPhoneApp`: Apple Watch와 Windows 사이의 중계 앱
- `apple/WatchApp`: 손목 제스처 및 버튼·Digital Crown 입력
- `apple/project.yml`: XcodeGen 프로젝트 정의

## 1. Windows 실행

[.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0)이 설치되어 있어야 합니다.

PowerShell에서:

```powershell
cd windows
dotnet run
```

서버 권한 오류가 표시되면 관리자 PowerShell에서 안내된 `netsh` 명령을 한 번 실행합니다.
Windows 방화벽이 묻는 경우 개인 네트워크 접근을 허용합니다.

## 2. Mac에서 Apple 프로젝트 열기

Mac에 Xcode와 XcodeGen을 설치한 다음:

```bash
cd apple
brew install xcodegen
xcodegen generate
open GestureRemote.xcodeproj
```

Xcode에서 iPhone 및 Watch 타깃의 Team을 자신의 Apple ID 팀으로 바꾸고,
Bundle Identifier도 고유한 값으로 변경합니다. 실제 iPhone을 대상으로 실행하면
페어링된 Apple Watch 앱도 설치됩니다.

## 3. 연결

1. Windows 수신기를 실행하고 화면에 표시된 IP 주소를 확인합니다.
2. iPhone과 Windows를 같은 Wi-Fi에 연결합니다.
3. iPhone 앱에 Windows IP 주소를 입력하고 연결합니다.
4. Watch 앱에서 `제스처 켜기`를 누릅니다.

## 기본 조작

- 손목 X축 튕김: 이전/다음
- 손목 Y축 튕김: 위/아래 스크롤
- Digital Crown: Windows 볼륨
- Watch의 `−`, `+`: 축소/확대
- 재생 버튼: 미디어 재생/일시정지
- AssistiveTouch: 화면의 버튼을 포커스하고 주먹 쥐기로 실행

초기 임계값은 `3.0 rad/s`, 재입력 방지 시간은 `0.8초`입니다.
실사용 시 사용자 움직임에 맞춰 보정해야 합니다.

## MacBook 제어

`xcodegen`으로 프로젝트를 다시 생성하면 `GestureRemoteMac` 타깃이 추가됩니다.
해당 타깃의 Team을 설정한 뒤 `My Mac`을 대상으로 실행합니다. 메뉴 막대의
Apple Watch 아이콘에서 Mac의 Wi-Fi IP를 확인하고 iPhone 앱에 입력합니다.
처음 실행할 때 macOS가 손쉬운 사용 권한을 요청하면 허용한 뒤 앱을 다시 실행합니다.

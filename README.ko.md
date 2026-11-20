# t3code-sync — T3 Codex 자동 갱신

**Windows 미리보기 버전입니다.** T3 Code 0.1.9 / 데이터베이스 마이그레이션 81 및 지정된 스키마에서 검증한 로컬 실행 도구입니다. Linux와 macOS는 아직 지원하지 않습니다. T3 Tools 및 OpenAI와 무관한 독립 커뮤니티 도구입니다.

[Windows 다운로드](https://github.com/IEDGEI/t3code-sync/releases/tag/v1.0.2-windows-preview) · [English](README.md) · [복구 및 제거](docs/RECOVERY.md)

## Windows 설치

1. Python 3.9 이상과 Node.js 22.13 이상을 설치하고, T3와 Codex를 한 번 실행합니다.
2. T3에 갱신할 Codex 대화를 먼저 가져옵니다.
3. [설치 ZIP](https://github.com/IEDGEI/t3code-sync/releases/tag/v1.0.2-windows-preview)의 압축을 풀고 `Install.cmd`를 실행합니다.
4. 설치 후 T3를 완전히 닫고 바탕화면의 **T3 Code (Auto Sync)**로 실행합니다.

설치 프로그램은 T3·Python·Node.js 위치와 T3 데이터 호환성을 확인합니다. 런타임을 자동으로 다운로드하지 않습니다.
설치 패키지는 프로그램만 포함하며, 컴퓨터 사이의 대화나 파일을 전송하지 않습니다.

## 사용

설치 후 바탕화면의 **T3 Code (Auto Sync)** 또는 변경된 기존 T3 바로가기로 실행합니다.
T3가 완전히 종료되어 있으면, 이미 가져온 Codex 대화의 새 메시지를 반영한 뒤 T3를 엽니다.
T3가 이미 실행 중이면 기록을 수정하지 않고 기존 창을 엽니다. 갱신하려면 T3를 닫은 뒤 해당 바로가기로 다시 실행하세요.
원래 실행 파일을 직접 실행하면 자동 갱신 과정을 거치지 않습니다.

기존 설치된 Python 3.9 이상과 Node.js 22.13 이상의 기본 SQLite 기능을 사용합니다. 네트워크 요청이나 추가 패키지 설치는 없습니다.

## 갱신 범위

- 이미 T3에 가져온 Codex 대화에 완료되거나 중단된 턴의 사용자·답변 메시지만 추가합니다.
- Codex의 원본 데이터는 읽기 전용으로 접근합니다.
- Codex 내부 설정, AGENTS 지침, 도구 출력 등은 새 메시지로 추가하지 않습니다.
- 프로젝트 및 새 대화 발견·최초 가져오기는 T3의 Welcome 화면을 사용합니다.
- T3에서 이어 쓴 대화, 원본이 달라진 대화, 원본이 없거나 압축된 대화는 건너뛰고 이유를 로그에 기록합니다.
- 기존 가져오기에서 빠진 과거 메시지를 복구하거나 이미지·도구 실행 내역을 복제하는 도구는 아닙니다.
- 한 번에 최대 500개 메시지를 추가합니다. 남은 메시지는 다음 실행 시 처리합니다.
- T3의 버전/DB 구조가 지원 범위를 벗어나면 기록을 수정하지 않습니다.

## 저장과 복구

설치 경로: `%USERPROFILE%\.t3\tools\codex-autosync`

실행 기록과 백업: `%USERPROFILE%\.t3\codex-autosync`

- `last-sync.json`: 최근 결과, 대화별 추가 메시지 수, 건너뛴 이유
- `sync.log`: 실행 결과 기록. 대화 본문은 기록하지 않습니다.
- `backups\statev2-before-sync-*.sqlite`: 매 변경 전 무결성을 확인한 전체 DB 백업
- `shortcut-backups`: 변경 전 바로가기

프로그램은 정규 이벤트, 화면용 projection, 검색 인덱스, 타임라인 순서와 체크포인트를 하나의 트랜잭션으로 반영합니다.
트랜잭션 중 T3가 켜지거나 원본 기록이 변경되면 쓰기를 취소합니다.

복구가 필요하면 T3를 완전히 종료한 뒤 현재 `userdata` 폴더를 별도로 보관하고,
백업 DB를 `%USERPROFILE%\.t3\userdata\statev2.sqlite`로 복원합니다.
기존 WAL/SHM이 있다면 함께 별도 보관해야 합니다. 실행 중인 DB에 백업을 덮어쓰지 마세요.

자동 갱신을 끄려면 원래 T3 실행 파일로 실행하거나 `shortcut-backups`의 기존 바로가기를 복원하세요.

## 개발과 진단

```powershell
python "$env:USERPROFILE\.t3\tools\codex-autosync\autosync.py" --preview
python "$env:USERPROFILE\.t3\tools\codex-autosync\autosync.py" --apply
python "$env:USERPROFILE\.t3\tools\codex-autosync\autosync.py" --launch
```

저장소 루트에서 개발 검증 및 설치:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python scripts/build_package.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Preview
.\scripts\Install.cmd
```

실행 코드는 `src/`, 설치·패키징 스크립트는 `scripts/`, 테스트는 `tests/`, 보조 문서는 `docs/`에 있습니다.

`config.json`에는 T3 실행 파일, T3/Codex 데이터 폴더와 결과 저장 폴더를 지정합니다.
설치 프로그램은 `T3CODE_HOME`과 `CODEX_HOME`을 우선 사용하며, 지정하지 않으면 사용자 폴더의 `.t3`와 `.codex`를 사용합니다.
T3 업데이트 후 DB 구조가 바뀌면 호환성을 재검증해야 합니다.

구현 시 로컬 설치본의 `AgentSessionImporter` 이벤트 형식과 Codex JSONL 기록 형식을 확인했습니다.

## 라이선스와 상태 확인

MIT 라이선스입니다. T3 코드에서 참고·적용한 스키마와 이벤트 형식의 저작권 고지는 [THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md)와 [상위 프로젝트 라이선스](licenses/T3-CODE-MIT.txt)에 보존했습니다.
갱신 오류가 나면 상태 파일에 오류를 기록한 뒤에도 T3가 열릴 수 있습니다. 갱신 성공 여부는 `last-sync.json`에서 확인하세요.
로그에는 대화 제목·식별자·개인 경로가 포함될 수 있고 백업에는 대화 DB가 들어 있으므로 공유하기 전에 내용을 확인하세요.

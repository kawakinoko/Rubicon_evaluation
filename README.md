# Rubicon_evaluation

Rubicon Evaluation

## Quick Start

Repository root에서도 바로 실행할 수 있다.

```bash
cd /workspaces/Rubicon_evaluation
bash setup_and_run.sh
```

실제 실행 스크립트는 [samsung-rubicon-qa/scripts/setup_and_run.sh](samsung-rubicon-qa/scripts/setup_and_run.sh) 에 있다.

## Share Bundle

공유용 zip 을 다시 만들려면 아래를 실행한다.

```bash
cd /workspaces/Rubicon_evaluation
bash share_bundle/build_share_bundle.sh
```

생성 결과물은 [rubicon-qa-share.zip](rubicon-qa-share.zip) 이다. 이 zip 안에는 payload 압축 파일과 함께 압축 해제 및 git 브랜치 생성을 자동화하는 `setup_bundle.sh`, `setup_bundle.bat` 가 들어간다.

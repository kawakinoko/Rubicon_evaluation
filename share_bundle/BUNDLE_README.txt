Rubicon Evaluation share bundle

Contents
- rubicon-evaluation-payload.zip: repository payload
- setup_bundle.sh: unzip payload, initialize git, create branch, optional origin remote
- setup_bundle.bat: Windows version of the same flow

Usage on Linux or macOS
1. unzip this bundle zip
2. run: bash setup_bundle.sh [target_parent_dir] [branch_name] [remote_url]

Usage on Windows
1. extract this bundle zip
2. run: setup_bundle.bat [target_parent_dir] [branch_name] [remote_url]

Examples
- bash setup_bundle.sh /tmp demo/rubicon https://github.com/example/repo.git
- setup_bundle.bat C:\temp demo/rubicon https://github.com/example/repo.git

Notes
- The extracted repository includes the committed Samsung storage state file used by GitHub Actions.
- OPENAI_API_KEY is still optional. Without it, execution continues and evaluation falls back.
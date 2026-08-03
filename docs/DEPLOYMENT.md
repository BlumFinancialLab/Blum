# BLUM Deployment and Repository Synchronization

BLUM uses two public Git repositories with distinct responsibilities:

- `origin`: `https://github.com/BlumFinancialLab/Blum.git`, the canonical
  source, review and community repository;
- `hf`: `https://huggingface.co/spaces/Italianhype/Blum`, the public Docker
  Space deployment.

## Local development

```bash
git clone https://github.com/BlumFinancialLab/Blum.git
cd Blum
docker build -t blum .
docker run --rm -p 7860:7860 blum
```

Secrets belong in the local environment or deployment secret store. They must
never be committed.

## Hugging Face to GitHub

`.github/workflows/sync-huggingface.yml` reads the public Space repository twice
an hour and can also be dispatched manually. It uses commit ancestry rather
than timestamps:

| Relationship | Action |
| --- | --- |
| Same revision | No change |
| HF is behind GitHub | No change |
| HF is strictly ahead | Fast-forward GitHub after LFS transfer |
| Histories diverged | Update `sync/hf-main` and open a pull request |

The workflow does not use an HF token because the Space Git repository is
public. It never force-pushes `main`. A rejected fast-forward falls back to the
review branch.

Manual run:

```bash
gh workflow run sync-huggingface.yml --repo BlumFinancialLab/Blum
gh run list --repo BlumFinancialLab/Blum --workflow sync-huggingface.yml
```

## GitHub to Hugging Face

Deployment remains an explicit maintainer action:

```bash
git fetch origin main
git push hf origin/main:main
```

Keeping this direction explicit prevents a public GitHub workflow from needing
an HF write credential. A future automated deploy must use a scoped repository
secret and a separate reviewed workflow.

## Startup and readiness

The Space uses startup-light behavior: the UI may become available while the
persistent database finishes restoring. Check:

```bash
curl -fsSL https://italianhype-blum.hf.space/startup/status
```

The release is ready when `api_ready` and `ui_ready` are true and the runtime
reports no `last_error`.

## Recovery

- Workflow cannot fetch HF: rerun after confirming the Space repository is
  public and available.
- LFS transfer fails: GitHub `main` remains unchanged; rerun the workflow.
- Histories diverge: review the generated pull request and preserve both sides.
- Space build fails: inspect HF build logs and keep GitHub as the known source
  revision; do not rewrite history to hide the failure.

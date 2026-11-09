# Releasing

Publishing a GitHub release publishes that version to PyPI. The workflow is [`.github/workflows/release.yml`](../.github/workflows/release.yml).

**A release cannot be taken back.** PyPI never accepts the same version twice, and deleting a release leaves copies on mirrors. A wheel holds the source code, so the first real release also makes the code public, even while the repository is private. Decide that first: see [going-public.md](going-public.md).

## What the workflow does

| Job | What it checks or does |
|---|---|
| Check | The release tag matches `version` in `pyproject.toml`, so `v0.2.0` publishes 0.2.0. Then ruff and the full test suite |
| Build | Builds the wheel and sdist, lists every file in both, and fails if it finds `.env`, a virtual environment, `.vscode/` or anything outside the package. Then `twine check --strict` |
| Publish | Uploads to PyPI through trusted publishing, in the `pypi` environment. No PyPI token is stored in GitHub |
| Attach | Adds the same files to the GitHub release |

Running the workflow by hand, from the Actions tab, runs Check and Build only. Use it as a dry run before a real release.

## One-time setup

1. **Add the trusted publisher on PyPI.** On <https://pypi.org/manage/project/glimpse-ai/settings/publishing/>, add a GitHub publisher with:
   - Owner: `axnsantana`
   - Repository: `glimpse-ai`
   - Workflow: `release.yml`
   - Environment: `pypi`
2. **Create the `pypi` environment on GitHub:** Settings, Environments, New environment, `pypi`. Add yourself as a required reviewer, so every publish waits for your approval. Under deployment branches and tags, allow only tags matching `v*`.
3. **Revoke the PyPI API tokens.** With trusted publishing, the workflow needs none, so the account-wide token used for the placeholder upload can go.

Trusted publishing has not been tried from a private repository yet. If the Publish job fails on attestations while the repository is private, add `attestations: false` to its `with:` block, or make the repository public first.

## Each release

1. **Set the version** in both `pyproject.toml` and `src/glimpse/__init__.py`. A test fails if they differ.
2. **Update `CHANGELOG.md`**, moving "unreleased" to the version and date.
3. **Check the NiceGUI advisories** with the command in [security.md](security.md), and raise the minimum if a new one applies.
4. **Merge to `main`**, and wait for CI to pass.
5. **Do a dry run:** Actions, Release, Run workflow. Read the file lists in the Build job.
6. **Publish the release**, with a tag named after the version:
   ```bash
   gh release create v0.1.0 --target main --title "0.1.0" --notes-file notes.md
   ```
   Add `--prerelease` for versions such as `0.2.0rc1`. Pip skips those unless asked for them.
7. **Approve the deployment** when GitHub asks, if you set a required reviewer.
8. **Check the result** on <https://pypi.org/project/glimpse-ai/>, then in a clean environment:
   ```bash
   python -m venv /tmp/try && /tmp/try/bin/pip install "glimpse-ai[anthropic]"
   /tmp/try/bin/python -c "import glimpse; print(glimpse.__version__)"
   ```

## If something goes wrong

- **The Check job fails on the tag.** Delete the release and its tag, then create it again with the right tag. Nothing was published.
- **Publish fails.** Nothing was uploaded. Fix the cause and run the failed jobs again from the Actions tab.
- **A broken version reached PyPI.** It cannot be replaced. Yank it on PyPI, so that pip stops choosing it, and release a new patch version.

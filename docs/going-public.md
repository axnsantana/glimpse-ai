# Going public

The repository is private for now, and these are the steps to make it public, in order. The presentation page in `site/` and its deploy workflow are ready, but neither has been deployed, because GitHub's free plan has no Pages for private repositories.

## Before anything is visible

1. **Check the history for secrets.** Making the repository public publishes every commit:
   ```bash
   git log --all --full-history -- .env
   git log --all -p | grep -nE 'sk-ant-|pypi-[A-Za-z0-9_-]{20,}'
   ```
   Both should print nothing. Rotate any key that appears, and rewrite the history before going on.
2. **Run every test:** `pytest`, `pytest -m e2e` and, if the prompt or tools changed, `pytest -m live -s`.
3. **Check the NiceGUI advisories** with the command in [security.md](security.md), and raise the minimum version if a new one applies.
4. **Update the numbers on `site/index.html`** if they changed: the test counts, the 26 of 26 result, and the example answers.
5. **Check the PyPI token.** Use a token scoped to `glimpse-ai`, and revoke the account-wide token used for the first upload.

## Make it public

These steps have effects that cannot be fully undone, because copies can be made once code is public.

1. **Make the repository public:** Settings, General, Danger Zone.
2. **Publish the real release.** Until now, PyPI has only held the empty placeholder `0.0.1`, so the install command on the page does not work until this is done.
   ```bash
   rm -rf dist && python -m build
   python -m zipfile -l dist/*.whl       # Check the contents first. An upload cannot be taken back
   tar tzf dist/*.tar.gz
   python -m twine check --strict dist/*
   python -m twine upload dist/*
   ```
   Check that the sdist holds no `.env`, virtual environment or other stray files. Hatchling follows `.gitignore`, but look anyway. Then try the release in a clean environment:
   ```bash
   python -m venv /tmp/try && /tmp/try/bin/pip install "glimpse-ai[anthropic]"
   ```
3. **Turn on Pages:** Settings, Pages, Build and deployment, Source: **GitHub Actions**.
4. **Deploy the page:** Actions, Pages, Run workflow. After this, every push to `main` that changes `site/` deploys it.
5. **Check the live page** at <https://axnsantana.github.io/glimpse-ai/>, including its links to the repository, which return 404 while it is private.
6. **Set the repository's website** to that address: `gh repo edit --homepage https://axnsantana.github.io/glimpse-ai/`.
7. **Update the README and getting started guide** to install from PyPI.

## Preview the page locally

```bash
python -m http.server --directory site 8000
```

Links to GitHub return 404 until the repository is public, and the rest of the page works.

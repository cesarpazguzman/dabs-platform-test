# dabs-platform-test

Platform repository for a Declarative Automation Bundles (DABs) demo on Databricks. It holds what the
**platform team** owns and every use case reuses:

| Path | What it is |
| --- | --- |
| `.github/workflows/bundle-ci.yml` | Reusable CI: validate, platform rules, unit tests, plan, deploy to qa and prd |
| `ci/check_rules.py` | Platform rules, checked on the resolved configuration of every PR |
| `templates/use-case/` | Template every new use case starts from (`databricks bundle init`) |
| `platform-bundle/` | Shared objects: schemas, landing volume and sample data |
| `STEPS.md` | Full setup log: every step, command, test and design decision |

The use cases live in [`dabs-use-cases-test`](https://github.com/cesarpazguzman/dabs-use-cases-test), one
bundle per folder. All data comes from `samples.tpch`.

## How it works

```
feature/*  ──PR──►  qa    ──push──►  deploy qa   (sp-dabs-qa, automatic)
qa         ──PR──►  main  ──push──►  deploy prd  (sp-dabs-prd, after approval)
hotfix/*   ──PR──►  main  ──push──►  deploy prd, then merge main back into qa
any branch ──laptop──►  dev  (personal copy, the developer's own user)
```

| Target | Branch | Deployed by | Identity |
| --- | --- | --- | --- |
| `dev` | any | the developer, from a laptop | the developer |
| `qa` | `qa` | CI, on merge | `sp-dabs-qa` |
| `prd` | `main` | CI, on merge and approval | `sp-dabs-prd` |

## What the CI enforces

- **`validate --strict`**: configuration warnings, such as a misspelled field, fail the PR.
- **Platform rules**: no catalogs or schemas in use-case bundles, job names prefixed with the bundle name,
  failure notifications and an `owner` tag on every job.
- **Branch policy**: only `qa` and `hotfix/*` can be merged into `main`, and a promotion from `qa` is blocked
  until any hotfix on `main` has been merged back into `qa`.
- **Unit tests**: run with a local Spark when the bundle has a `tests/` folder.
- **Safe deployments**: one deployment per bundle and environment at a time, and an older run can never
  overwrite a newer state (skipped in qa, refused in prd).
- **Identities**: each environment has its own service principal; the prd secret only reaches the prd job
  after a reviewer approves it.

## Use it from a use-case repository

Create a use case (only its name is asked):

```bash
databricks bundle init https://github.com/cesarpazguzman/dabs-platform-test --template-dir templates/use-case
```

The generated workflow calls the CI by version:

```yaml
jobs:
  ci:
    uses: cesarpazguzman/dabs-platform-test/.github/workflows/bundle-ci.yml@v1
    with:
      bundle_path: <use_case>
    secrets: inherit
```

The calling repository needs the secrets `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` and
`DATABRICKS_CLIENT_SECRET` (qa service principal), and the GitHub environments `qa` and `prd` (the latter
with reviewers and the prd service principal's secrets). See `STEPS.md`, section 5.10.

## Release a platform change

```bash
git commit -am "<change>" && git push
git tag -f v1 && git push -f origin v1
```

Every use case picks it up on its **next** run; re-runs of existing runs keep the previous version.
Template changes only affect new use cases.

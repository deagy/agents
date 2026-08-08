# Security

## Supply chain: the `agentic-sdlc` name on PyPI is not us

**This project is not published on PyPI.**

The distribution name `agentic-sdlc` on PyPI is owned by an unrelated
third-party project. Running:

```sh
pip install agentic-sdlc        # DO NOT DO THIS
```

installs *that* project — not this lifecycle kernel. It will install
successfully and look plausible, so the failure is silent: you get a working
package with the expected name that is not the software you intended to run.

There is no typo or malice required for this to happen. It is simply a name
collision, and it predates this project's use of the name.

### Install only from these sources

```sh
# From a checkout of this repository
pipx install ./kernel

# From a pinned git tag
pipx install "git+https://github.com/deagy/agentic-sdlc.git@v<version>#subdirectory=kernel"

# From a checkout, without installing anything
./bin/agentic-sdlc --help
```

Wheels and sdists attached to this repository's
[Releases](https://github.com/deagy/agentic-sdlc/releases) are also
authoritative. Verify them against the `SHA256SUMS` file published alongside
each release before installing.

### Verifying what you have

```sh
agentic-sdlc --version          # this kernel prints a bare semver, e.g. 0.13.0
pip show agentic-sdlc           # check the Home-page / Project-URL field
```

If `pip show` reports a homepage that is not `github.com/deagy/agentic-sdlc`,
you have the wrong package. Uninstall it before continuing.

### Automated installers

`plugin/tools/bootstrap_sdlc.py` installs this kernel from a checksum-verified
release asset (falling back to a pinned git tag), never from PyPI, for exactly
this reason.
If you write your own automation, do the same.

## Verifying a release

Release artifacts carry a SLSA provenance attestation, and release tags are
signed. Both use Sigstore keyless signing — an ephemeral certificate minted
from the release workflow's OIDC identity and recorded in the Rekor
transparency log — so there is no long-lived signing key anywhere in this
project to be stolen or rotated.

Artifacts, using the GitHub CLI:

```sh
gh release download kernel-v<version> --repo deagy/cadre
gh attestation verify agentic_sdlc-<version>-py3-none-any.whl --repo deagy/cadre
sha256sum -c SHA256SUMS
```

Tags, using [gitsign](https://github.com/sigstore/gitsign):

```sh
gitsign verify kernel-v<version> \
  --certificate-identity-regexp='https://github.com/deagy/cadre/' \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com
```

**GitHub's web UI shows these tags as "Unverified".** Its badge recognises
only GPG and SSH keys registered to a user account, and this project
deliberately has neither — a stored private key is the thing keyless signing
exists to avoid. Use the command above rather than the badge.

Each release also carries an SPDX SBOM: the kernel's records its resolved
Python dependency tree, and the plugin's records the Cline plugins' npm
tree, which is that distribution's only third-party surface.

The plugin distribution itself carries no artifact provenance, deliberately.
A marketplace installs it by cloning a git commit, so there is no downloaded
file to verify and integrity comes from git's content addressing. Signing a
tarball nobody installs from would prove something about a file no user
touches.

## Reporting a vulnerability

Open a
[security advisory](https://github.com/deagy/agentic-sdlc/security/advisories/new)
rather than a public issue.

## Security-relevant invariants

These are load-bearing properties of the kernel, not incidental validation.
Treat a change that weakens any of them as a security regression:

- Human authorities start **unassigned**; conditional applicability starts
  `unknown`, and unknown-applicable requirements **block** the gate.
- No gate is ever approved by `init`, `detect`, `plan`, or `validate`.
- G9 (Deployment Authorization) is `human_only` — automation cannot grant it.
- Author, independent reviewer, and human approver must be distinct
  identities; `validate_repository()` and the engine's gate-decision nodes
  both reject configurations where they are not.
- Approval evidence must reference an external authoritative system. Evidence
  is never invented, inferred, or silently migrated.
- Provider resource paths must resolve inside the manifest's own directory;
  path escape, duplicate IDs, and kernel-version incompatibility all fail
  closed.

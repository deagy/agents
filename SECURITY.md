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

Release artifacts carry a SLSA provenance attestation: an ephemeral
certificate minted from the release workflow's OIDC identity and recorded in
the Rekor transparency log, so there is no long-lived signing key anywhere in
this project to be stolen or rotated.

```sh
gh release download kernel-v<version> --repo deagy/cadre
gh attestation verify agentic_sdlc-<version>-py3-none-any.whl --repo deagy/cadre
sha256sum -c SHA256SUMS
```

Each release also carries an SPDX SBOM: the kernel's records its resolved
Python dependency tree, and the plugin's records the Cline plugins' npm
tree, which is that distribution's only third-party surface.

### Why tags are not signed

Release tags are unsigned annotated tags. Keyless tag signing via
[gitsign](https://github.com/sigstore/gitsign) was implemented and reverted:
it produced a valid-looking signature on the tag object but created no Rekor
entry, and a keyless certificate is ephemeral, so with nothing in the
transparency log there is nothing to verify the signature against. It failed
verification immediately at signing time and still failed hours later, with
the same gitsign version that produced it.

A signature nobody can verify is worse than none — it implies an assurance
that does not exist. The artifact attestations above are unaffected and do
reach Rekor; that difference is exactly what made the tag problem visible.

The alternative, a GPG or SSH key held in repository secrets, would give
GitHub's "Verified" badge and native `git verify-tag`, at the cost of a
long-lived private key — which is what the keyless posture exists to avoid.
That remains a deliberate open choice rather than an oversight.

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

# Setting up tag signing

One-time setup. Until it is done, releases still work — they simply produce
unsigned annotated tags and the workflow logs a warning, rather than failing.

## 1. Generate a signing key

Run this yourself. Do not have anyone generate it for you and paste it into
a chat or an issue; the private key should never leave your machine except
into the GitHub secret.

```sh
ssh-keygen -t ed25519 -f ~/.ssh/cadre-tag-signing -C "releases@cadre" -N ""
```

## 2. Store the private key as a repository secret

```sh
gh secret set TAG_SIGNING_KEY --repo deagy/cadre < ~/.ssh/cadre-tag-signing
```

The workflow reads it into a mode-600 file under `RUNNER_TEMP` for the
duration of the job.

## 3. Register the public key on your account, as a signing key

This is what makes GitHub display the tags as **Verified**. It must be added
as a *signing* key — an authentication key of the same name does not count.

```sh
gh ssh-key add ~/.ssh/cadre-tag-signing.pub --type signing --title "cadre tag signing"
```

## 4. Commit the public key so others can verify locally

```sh
cp ~/.ssh/cadre-tag-signing.pub .github/tag-signing-key.pub
git add .github/tag-signing-key.pub && git commit -m "chore: publish the tag signing public key"
```

Public keys are safe to commit; this is the file SECURITY.md points readers
at to build an `allowed_signers` entry.

## 5. Cut a release and check

Bump a version, let the workflow run, then confirm both:

```sh
git fetch --tags
git cat-file -p plugin-v<version> | grep -c "BEGIN SSH SIGNATURE"   # 1
gh api repos/deagy/cadre/git/ref/tags/plugin-v<version> --jq .object.sha \
  | xargs -I{} gh api repos/deagy/cadre/git/tags/{} --jq .verification
```

`verification.verified` should be `true`. If it is `false` with reason
`unknown_key`, step 3 was missed or the key was added as an auth key.

The workflow also verifies its own signature before pushing, and **fails the
release** if it does not check out — a tag that cannot be verified is the
defect, not something to log and continue past.

## Rotating

Repeat steps 1–4 with a new key and remove the old one from your account.
Tags signed with the retired key stop verifying against the current
`allowed_signers`, which is the expected cost of rotation; the tag objects
themselves are unchanged.

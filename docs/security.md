# Security

What EdgeLens guarantees, and what stays your responsibility.

## API key handling

- **Never commit keys.** Read them from the environment (`EDGELENS_API_KEY`),
  not from source.
- **The plaintext is shown once.** At creation the portal shows the key exactly
  once; after that only a hash is stored. If you lose it, mint a new one.
- **Revoke freely.** Revoke a key from the portal at any time; a revoked key is
  rejected immediately on its next request.

## Session isolation

Every session runs on its own dedicated device. There is no shared state
between sessions — a session gets a device to itself for its lifetime, and no
other customer is on that device at the same time.

## Wipe-on-release

When a session is released, the device's user data is wiped before it returns to
the pool. **State does not persist between sessions**, and never carries across
customers. Write your tests accordingly:

- Don't assume files, models, or processes from a previous session survive.
- Deploy everything the test needs at the start of the session.

## You own root

The device OS is yours for the session — you have full root access. With that
comes responsibility:

- **Don't ship secrets in your model bundle or on the device.** Anyone on your
  account can allocate the same session and read whatever you left there.
- **Treat the device as disposable.** Because of wipe-on-release, anything you
  want to keep must be pulled back before you release the session.

## The EdgeLens compatibility hook

Every EdgeLens-flashed device includes `/etc/edgelens/authorized_keys.d/` — an
initially-empty directory where per-session operator SSH keys are dropped. It
exists so we can grant temporary access to the device for the duration of your
session without patching your OS's arbitrary paths.

**You are welcome to strip it** if you never plan to run this OS on the EdgeLens
platform. Remove the directory and the corresponding `AuthorizedKeysFile
/etc/edgelens/authorized_keys.d/*.pub` line from `sshd_config`.

**Planned:** uploading a customized base image back to EdgeLens
(Bring-Your-Own-Image) is planned and not yet available. When it ships, this
hook is where upload-time patching will drop the session key. If the hook is
missing, upload-time patching will fall back to `/root/.ssh/authorized_keys`
and issue a compatibility warning.

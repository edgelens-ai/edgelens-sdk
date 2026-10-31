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
the pool. **State does not persist between sessions.** Write your tests
accordingly:

- Don't assume files, models, or processes from a previous session survive.
- Deploy everything the test needs at the start of the session.

## You own root

The device OS is yours for the session — you have full root access. With that
comes responsibility:

- **Don't leave secrets on the device or in your model bundle.** Anything on
  the device is readable by whoever holds the session, and by any code you
  deploy to it, until the session is released.
- **Treat the device as disposable.** Because of wipe-on-release, anything you
  want to keep must be pulled back before you release the session.

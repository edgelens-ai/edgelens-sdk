# Models / binaries

This example expects:

- `face.cvimodel` in this directory, uploaded with
  `device.deploy({ model: { name, blob } })`.
- For the recamagined test, a `./build/my_inference` binary built for
  RISC-V (the reCamera target). Run your cross-compile here. The test
  uploads it as a deploy file and runs `chmod +x` on it before executing,
  because deployed files arrive without the executable bit.

For your own project, swap these references and run.

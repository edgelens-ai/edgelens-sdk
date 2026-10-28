# Models

Drop your `.cvimodel` files here. `bench_sweep.py` expects three
versioned files (`face_v3.0.0`, `face_v3.1.0`, `face_v3.2.1`); edit
the `MODELS` list to match your reality.

`bench_single.py` takes any path via `--model`.

Tip: gitignore real models; commit a download script or a pointer to
S3/GCS.

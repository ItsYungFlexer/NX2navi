# Rendering stability changes

These changes address two concrete failure paths relevant to
[upstream issue 6](https://github.com/tangerineturtle1/NX2navi/issues/6).
They are not a claim that every source of incorrect lighting or AMD artifacts is resolved.

## Missing passes during compilation

The default `pipe_skip = none` waits for missing shaders and graphics pipelines,
including draws into targets used in the preceding frame. The previous default
could omit geometry, shadows and full-screen effects during compilation. Newly
visible objects and areas can therefore cause flashing or incomplete frames.

Cold compilation can pause rendering. The existing 30-second pipeline timeout and
failure reporting remain; failed translations are not repaired by this change.
Explicit `strict`, `any` and `fullscreen` settings keep their previous behavior.
To use the new default with an existing explicit override, set:

```ini
[performance]
pipe_skip = none
```

## Brightness decode after resolution changes

The fallback upscaler caches eight scratch images by dimensions and format.
Previously, a ninth distinct request returned no image permanently. If the RGB9E5
scratch image could not be obtained, the fallback blitted the packed bits using
the original R11G11B10 format and skipped the square decode. Those formats encode
different values; this is not an exposure adjustment.

The cache now replaces its least recently used entry after successfully allocating
a replacement. Associated sampling views are removed from the tonemap cache, and
both views and images use the existing fence-aware deferred destruction path.
Allocation failure preserves the old entry. Memory remains bounded to eight cached
images plus resources awaiting their GPU fence.

## Checks

- `tests/render_fallback_test.py` compiles the actual cache and view functions with
  Vulkan allocation/destruction mocks. It checks hits, 40 additional sizes,
  allocation failure, view invalidation before image retirement, multiple views,
  and all pipeline-skip mode names and numeric aliases.
- `--probe-cfg` checks the new default and preservation of an explicit legacy mode.
- Changed runtime translation units were compiled with UCRT64 Clang and linked
  with the existing local game build objects for testing.
- The general `--selftest` reports a physical-memory pool assertion in both the
  unchanged installed executable and the patched executable.
- `--probe-vkexec` cannot complete its draw checks without the generated shader
  census (`build/v111/shaders/jobs.json`); device initialization reported zero
  validation errors, which does not establish rendering correctness.

For visual verification, compare the same save and camera before and after, first
with a cold pipeline cache and then warm. Enter new areas, pan across newly visible
geometry, and switch render/window resolutions repeatedly. Check both SDR and HDR
separately. A remaining persistent haze needs a frame capture of the lighting,
composition and upscaler passes; lowering final display brightness would conceal
the symptom without identifying that cause.

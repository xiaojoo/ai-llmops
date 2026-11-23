# Task 3 Report: MemoryProviderResolver（应用覆盖 > 系统默认 > builtin）

**Status: DONE**
**Commit: `8d56da5` feat(memory): MemoryProviderResolver 优先级解析（应用>系统>builtin）**
**Branch: `release_20260829`**

## What I implemented

1. **`internal/service/memory_provider/resolver.py`** (new) — `MemoryProviderResolver` (@inject dataclass) with `resolve(app_config) -> MemoryProvider` implementing precedence:
   - 1) App override: `long_term_memory.provider` — `builtin` → builtin; `tencent` → tencent; `default`/missing → fall through to system.
   - 2) System default: `SystemConfigService.get_config("MEMORY_PROVIDER")` — `tencent` → tencent; unknown non-empty value → warning log + fall back.
   - 3) Default: builtin.
   - Exports constants `BUILTIN = "builtin"`, `TENCENT = "tencent"`, `SYSTEM_MEMORY_PROVIDER_KEY = "MEMORY_PROVIDER"`.
2. **`internal/service/memory_provider/tencent_provider.py`** (new) — minimal skeleton: `TencentMemoryProvider(MemoryProvider)` @inject dataclass with the four abstract methods each raising `NotImplementedError("Task 7 填充")`. No real implementation (Task 7).
3. **`internal/service/memory_provider/__init__.py`** (modified) — full 4-symbol export: `MemoryProvider`, `MemoryReadContext`, `BuiltinMemoryProvider`, `TencentMemoryProvider`, `MemoryProviderResolver` in `__all__`.
4. **`internal/service/__init__.py`** (modified) — appended `from .memory_provider import MemoryProviderResolver` at the END of the import block (after `reflection_service`/`sub_task_service`, before `__all__`); added `"MemoryProviderResolver"` to `__all__` in alphabetical position (between `LtpService` and `MiniIoService`, keeping the list's ordering convention).
5. **`test/internal/service/memory_provider/test_resolver.py`** (new) — 7 tests, verbatim from the brief.

## TDD Evidence

**RED** — before implementation:
```
$ python -m pytest test/internal/service/memory_provider/test_resolver.py -v
ImportError while importing test module 'test\internal\service\memory_provider\test_resolver.py'
E   ImportError: cannot import name 'MemoryProviderResolver' from 'internal.service.memory_provider' (...)
======================== 2 warnings, 1 error in 0.40s =========================
```

**GREEN** — focused test (7/7):
```
test_resolver.py::TestResolver::test_defaults_to_builtin PASSED
test_resolver.py::TestResolver::test_system_tencent PASSED
test_resolver.py::TestResolver::test_app_override_tencent_beats_system_builtin PASSED
test_resolver.py::TestResolver::test_app_default_follows_system PASSED
test_resolver.py::TestResolver::test_invalid_system_value_falls_back_to_builtin PASSED
test_resolver.py::TestResolver::test_invalid_app_provider_falls_back_to_system PASSED
test_resolver.py::TestResolver::test_missing_long_term_memory_config PASSED
======================== 7 passed, 1 warning in 0.03s =========================
```

**Memory provider suite** (`pytest test/internal/service/memory_provider/ -x`): `15 passed` (Task 1–3 all green).

**Full suite** (`pytest test/ -x`):
```
FAILED test/internal/service/test_episodic_memory_service.py::TestEpisodicSearch::test_search_fuses_and_ranks
================= 1 failed, 151 passed, 11 warnings in 22.19s =================
```
The single failure is the known pre-existing one (episodic search fusion/ranking, line 117 AssertionError). Verified pre-existing: with my changes stashed (`git stash push`), the same test fails identically on clean HEAD `a94465c` (`1 failed`), and the test file contains zero references to `memory_provider`. Unrelated to Task 3.

The `PytestCacheWarning ... WinError 5` cache warning appears throughout — known/harmless, ignored per task notes.

## Files changed (commit 8d56da5 — exactly the brief's 5 paths, nothing else)

- `internal/service/memory_provider/resolver.py` (new, 43 lines)
- `internal/service/memory_provider/tencent_provider.py` (new, 34 lines)
- `internal/service/memory_provider/__init__.py` (modified)
- `internal/service/__init__.py` (modified, +2 lines)
- `test/internal/service/memory_provider/test_resolver.py` (new, 51 lines)

## Self-review findings

1. **Verbatim transcription**: `resolver.py`, `tencent_provider.py`, and the test file match the brief's code blocks line-for-line (verified by readback). `memory_provider/__init__.py` matches the brief's export block; the pre-existing shebang + module docstring (already in the file from Task 1/2) were preserved — the brief's snippet only shows the export block and removing the header would be a regression.
2. **`internal/service/__init__.py` placement**: import is at the very end of the import block (after `reflection_service`, before `__all__`), so `system_config_service` (imported at line 43) precedes it — no circular import. Confirmed working at runtime: the resolver test's `injector.get(MemoryProviderResolver)` exercises the full import chain.
3. **Tests assert real precedence behavior**: all 7 cases cover app-override > system > builtin, fallbacks (invalid app → system; invalid system → builtin), `default` follows system, and missing `long_term_memory` → builtin. All pass.
4. **No extras (YAGNI)**: `tencent_provider.py` is exactly the minimal skeleton (class + 4 `NotImplementedError` methods, no logic); no files outside the brief's paths created or staged; commit contains exactly 5 files (`git show --stat` verified — unchanged `base.py`/`builtin_provider.py` staged as no-ops, contributing nothing).
5. **Constraints honored**: Python 3.12, no new dependencies (only `injector`, already in use); precedence matches the spec.

## Concerns

- None blocking. Minor notes: (a) `memory_provider/__init__.py` retains its pre-existing header lines (intentional, see above); (b) `MemoryProviderResolver` was inserted alphabetically into `__all__` rather than appended at the end, to preserve the file's existing alphabetical convention — functionally equivalent, verified by green tests.

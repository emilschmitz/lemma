"""Menu profiles: one name (``LEMMA_MENU``) sets every axis of what the agent is optimizing.

Axes, each independently selectable on top of a profile:

- ``style`` (``declarative`` | ``imperative``; names live in ``research_loop/spec_styles.py``). One style moves a GROUP of parts together: ``emitter`` (SQL to spec
  text), ``assembler``, ``admission``, ``workspace`` (prompt builder + agent-visible mounts + lemma
  index) and ``measure``.
- ``trusted_set``, chosen within a style: ``rocketship`` (today's product path), ``fast``,
  ``adversary_imperativespec0`` (imperative) and ``declarative_default`` (declarative host lemma block).
  It selects the host lemmas/axioms/bridges pasted into the spec and listed in the lemma index.
- ``assumption_package`` (the catalog; ``LEMMA_ASSUMPTION_PACKAGE``).
- ``agent`` (model slug).
- ``speed_bar_mult`` (``LEMMA_SPEED_BAR_MULT``).

Overrides: ``LEMMA_SPEC_STYLE``, ``LEMMA_TRUSTED_SET``, ``LEMMA_ASSUMPTION_PACKAGE``,
``LEMMA_SPEED_BAR_MULT``, ``LEMMA_AGENT_MODEL`` (the launcher's ``--agent``) each override ONE axis. An
override that contradicts a value the profile sets fails loudly unless ``allow_override`` (the
launcher's ``--allow-override``, env ``LEMMA_MENU_ALLOW_OVERRIDE=1``). A trusted set that does not
belong to the style fails always. Every registry key points at an EXISTING function.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from research_loop.spec_styles import DECLARATIVE, ENV_VALUE, IMPERATIVE, STYLES, check_style, style_from_env
from research_loop.trust_configs import get_config

AXES = ("style", "trusted_set", "assumption_package", "agent", "speed_bar_mult")
ENV_OF_AXIS = {
    "style": "LEMMA_SPEC_STYLE",
    "trusted_set": "LEMMA_TRUSTED_SET",
    "assumption_package": "LEMMA_ASSUMPTION_PACKAGE",
    "agent": "LEMMA_AGENT_MODEL",
    "speed_bar_mult": "LEMMA_SPEED_BAR_MULT",
}


@dataclass(frozen=True)
class MenuProfile:
    name: str
    style: str
    trusted_set: str
    default_model: str
    assumption_package: str | None = None
    speed_bar_mult: str | None = None


# --- style group: emitter, assembler, admission, workspace, measure move together ---


@dataclass(frozen=True)
class Workspace:
    prompt: Callable
    mount: Callable[[Path], None]


@dataclass(frozen=True)
class StyleGroup:
    emitter: Callable
    assembler: Callable
    admission: Callable
    workspace: Workspace
    measure: Callable


def _mount_none(ro: Path) -> None:
    """Recursive path: no Verus docs / lemma indexes are mounted into context/ro."""


def _declarative_group() -> StyleGroup:
    from declarative_spec.admit import admit_declarative_body
    from declarative_spec.assemble import assemble_declarative_program
    from declarative_spec.drive import mount_verus_docs
    from declarative_spec.emit import emit_declarative_spec
    from declarative_spec.prompt import build_declarative_prompt
    from research_loop.decl_query_measure import write_query_measure

    return StyleGroup(
        emitter=emit_declarative_spec,
        assembler=assemble_declarative_program,
        admission=admit_declarative_body,
        workspace=Workspace(prompt=build_declarative_prompt, mount=mount_verus_docs),
        measure=write_query_measure,
    )


def _imperative_group() -> StyleGroup:
    from research_loop.admit_runquery import admit_runquery_body
    from research_loop.agent_sandbox import build_agent_prompt
    from research_loop.assemble_verified_program import assemble_verified_program
    from research_loop.harness import run_custom_sql_pipeline
    from verus_transpiler import transpile_sql_to_verus

    return StyleGroup(
        emitter=transpile_sql_to_verus,
        assembler=assemble_verified_program,
        admission=admit_runquery_body,
        workspace=Workspace(prompt=build_agent_prompt, mount=_mount_none),
        measure=run_custom_sql_pipeline,
    )


STYLE_GROUPS: dict[str, Callable[[], StyleGroup]] = {
    DECLARATIVE: _declarative_group,
    IMPERATIVE: _imperative_group,
}


# --- trusted sets: name -> (style it belongs to, TrustConfig of its flags, loader of the piece) ---


@dataclass(frozen=True)
class TrustedSetEntry:
    style: str
    trust: str  # key of research_loop.trust_configs.CONFIGS (the LEMMA_* flags)
    load: Callable[[], Any]


def _flag_driven(trust: str) -> Callable[[], Any]:
    """Imperative: the host lemmas are the existing flag-driven selection of that trust config."""
    return lambda: get_config(trust)


def _declarative_default() -> Any:
    from declarative_spec.trusted_sets import get

    return get("declarative_default")


TRUSTED_SETS: dict[str, TrustedSetEntry] = {
    "rocketship": TrustedSetEntry(IMPERATIVE, "product", _flag_driven("product")),
    "fast": TrustedSetEntry(IMPERATIVE, "fast", _flag_driven("fast")),
    "adversary_imperativespec0": TrustedSetEntry(
        IMPERATIVE, "adversary_imperativespec0", _flag_driven("adversary_imperativespec0")
    ),
    "declarative_default": TrustedSetEntry(DECLARATIVE, "adversary_declarative0", _declarative_default),
}

PROFILES: dict[str, MenuProfile] = {
    p.name: p
    for p in (
        MenuProfile("rocketship", IMPERATIVE, "rocketship", "grok-4.7-high"),
        MenuProfile("adversary_imperativespec0", IMPERATIVE, "adversary_imperativespec0", "grok-4.7-high"),
        MenuProfile("fast", IMPERATIVE, "fast", "grok-4.7-high"),
        MenuProfile(
            "adversary_declarative0", DECLARATIVE, "declarative_default",
            "claude-haiku-4-5-20251001", speed_bar_mult="1.0",
        ),
    )
}


def get_profile(name: str) -> MenuProfile:
    if name not in PROFILES:
        raise ValueError(f"unknown menu {name!r}; known: {', '.join(sorted(PROFILES))}")
    return PROFILES[name]


def check_style_trusted_set(style: str, trusted_set: str) -> None:
    check_style(style)
    if trusted_set not in TRUSTED_SETS:
        raise ValueError(f"unknown trusted_set {trusted_set!r}; known: {sorted(TRUSTED_SETS)}")
    belongs = TRUSTED_SETS[trusted_set].style
    if belongs != style:
        raise ValueError(f"trusted_set {trusted_set!r} belongs to the {belongs} style, not {style}")


# --- resolution ---


@dataclass(frozen=True)
class Resolved:
    menu: str
    values: dict[str, str | None]
    sources: dict[str, str]
    allow_override: bool = False

    @property
    def style(self) -> str:
        return self.values["style"]  # type: ignore[return-value]

    @property
    def trusted_set(self) -> str:
        return self.values["trusted_set"]  # type: ignore[return-value]

    def summary(self) -> str:
        rows = [f"  {axis:<18} {self.values[axis]!s:<28} [{self.sources[axis]}]" for axis in AXES]
        return f"menu {self.menu}\n" + "\n".join(rows)

    def as_dict(self) -> dict[str, Any]:
        return {
            "menu": self.menu,
            "allow_override": self.allow_override,
            "axes": {a: {"value": self.values[a], "source": self.sources[a]} for a in AXES},
        }


def _axis(
    axis: str, profile_value: str | None, overrides: list[tuple[str, str]], allow: bool
) -> tuple[str | None, str]:
    distinct = {v for _, v in overrides}
    if len(distinct) > 1:
        raise ValueError(f"axis {axis}: conflicting overrides {overrides}")
    if not overrides:
        return profile_value, "profile" if profile_value is not None else "unset"
    source, value = overrides[0]
    if value == profile_value:
        return value, f"profile (confirmed by {source})"
    if profile_value is not None and not allow:
        raise ValueError(
            f"axis {axis}: override {source}={value!r} contradicts the profile value {profile_value!r}; "
            "pass --allow-override (LEMMA_MENU_ALLOW_OVERRIDE=1) to override it"
        )
    return value, f"override {source}"


def resolve_menu(
    name: str,
    *,
    flags: dict[str, str] | None = None,
    allow_override: bool | None = None,
) -> Resolved:
    """Profile values + per-axis overrides (env vars and launcher ``flags``) -> resolved selection.

    ``flags`` maps an axis name to a launcher flag value (``--style``, ``--agent``, ...).
    """
    profile = get_profile(name)
    flags = flags or {}
    if allow_override is None:
        allow_override = os.environ.get("LEMMA_MENU_ALLOW_OVERRIDE", "") == "1"
    base = {
        "style": profile.style,
        "trusted_set": profile.trusted_set,
        "assumption_package": profile.assumption_package,
        "agent": profile.default_model,
        "speed_bar_mult": profile.speed_bar_mult,
    }
    values: dict[str, str | None] = {}
    sources: dict[str, str] = {}
    for axis in AXES:
        overrides: list[tuple[str, str]] = []
        env_val = os.environ.get(ENV_OF_AXIS[axis], "").strip()
        if env_val:
            overrides.append((ENV_OF_AXIS[axis], style_from_env(env_val) if axis == "style" else env_val))
        if axis in flags:
            flag = check_style(flags[axis]) if axis == "style" else flags[axis]
            overrides.append((f"--{axis.replace('_', '-')}", flag))
        values[axis], sources[axis] = _axis(axis, base[axis], overrides, allow_override)
    check_style_trusted_set(values["style"], values["trusted_set"])  # type: ignore[arg-type]
    return Resolved(name, values, sources, allow_override)


_active: Resolved | None = None
_saved: dict[str, str | None] = {}


def active_menu() -> Resolved | None:
    return _active


def activate_menu(
    name: str,
    *,
    flags: dict[str, str] | None = None,
    allow_override: bool | None = None,
) -> Resolved:
    """Resolve, print the selection, and apply its env for the rest of the process.

    Idempotent for the menu that is already active. ``deactivate_menu()`` restores the env.
    """
    global _active
    if _active is not None:
        if _active.menu == name:
            return _active
        raise RuntimeError(f"menu {_active.menu!r} is already active; cannot activate {name!r}")
    resolved = resolve_menu(name, flags=flags, allow_override=allow_override)
    trust = get_config(TRUSTED_SETS[resolved.trusted_set].trust)
    env = {**trust.env, "LEMMA_TRUST_CONFIG": trust.name, "LEMMA_MENU": name}
    for axis in AXES:
        if resolved.values[axis] is not None:
            val = str(resolved.values[axis])
            env[ENV_OF_AXIS[axis]] = ENV_VALUE[val] if axis == "style" else val
    for key, val in env.items():
        _saved[key] = os.environ.get(key)
        os.environ[key] = val
    _active = resolved
    print(f"[menu] resolved selection\n{resolved.summary()}", flush=True)
    return resolved


def record_effective_axis(axis: str, value: str, source: str) -> Resolved:
    """An axis the profile left unset got its value later (a launcher default): the active selection, and so the
    manifest and the printed RESULT, must name it rather than keep saying `unset`."""
    global _active
    assert _active is not None and _active.values[axis] is None
    _active = replace(_active, values={**_active.values, axis: value}, sources={**_active.sources, axis: source})
    print(f"[menu] {axis} = {value} [{source}]", flush=True)
    return _active


def deactivate_menu() -> None:
    global _active
    for key, old in _saved.items():
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old
    _saved.clear()
    _active = None


def activate_menu_from_env() -> Resolved | None:
    """``LEMMA_MENU`` -> activate; unset -> None (today's behavior, no profile)."""
    name = os.environ.get("LEMMA_MENU", "").strip()
    if not name:
        return None
    return activate_menu(name)


def style_group_for(resolved: Resolved) -> StyleGroup:
    return STYLE_GROUPS[resolved.style]()


def trusted_set_for(resolved: Resolved) -> Any:
    return TRUSTED_SETS[resolved.trusted_set].load()

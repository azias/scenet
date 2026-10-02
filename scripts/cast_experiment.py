"""Does Gemini's structured output cope with `cast` as a mapping? Measured, not assumed.

Issue #11 proposed a second, "agent-shaped" schema, `scenet schema --agent`, on the
hypothesis that `cast: dict[str, CastMember]` -- an object with dynamic keys -- fares
badly under constrained decoding, and that a flattened `cast: [{id, reference, ...}]`
would fare better. Nothing in Gemini's documentation says so either way. This script
asks the same model for the same panels under each schema shape and records how far
every answer gets: through the API, through JSON parsing, through validation (including
the `model_validator` checks no schema can express) and through a full compile to SVG.

**Arms.** Gemini takes a response schema in one of two request fields, and they are not
the same language:

- `responseJsonSchema` takes JSON Schema, `$defs`, `$ref` and `additionalProperties`
  included, so `PanelIR.model_json_schema()` goes in unchanged.
- `responseSchema` takes the older OpenAPI subset, which refuses `$defs`, `$ref`,
  `additionalProperties`, `const` and `default` outright ("Unknown name ... Cannot find
  field"). A schema has to be inlined to get in at all, and **a mapping cast cannot be
  expressed there**: without `additionalProperties` it is an object that says nothing
  about its values, which the arm built here sends as exactly that. The field also
  needs `propertyOrdering`, which `to_openapi` adds; see there for why.

Each field is crossed with both cast shapes; the JSON Schema arms are also crossed with
`additionalProperties: false` kept or stripped (`extra="forbid"` puts it on every object
in the IR), and with the published surface schema from `scenet schema`, which the how-to
guide recommends for this use.

**What is held fixed.** One model, one temperature, one seed per sample, the same
system instruction for every arm. The instruction lists the shipped puppets and says
nothing about the shape of `cast`; the schema is the only place that shape is stated.

**Network.** Nothing here runs under pytest except the pure functions, which
`tests/test_cast_experiment.py` covers. The API key is read from `GEMINI_API_KEY` when
set and sent only in the `x-goog-api-key` header; in an environment whose proxy injects
that header itself, no key is needed at all. It is never printed or written.

    uv run python scripts/cast_experiment.py run -o out/cast
    uv run python scripts/cast_experiment.py report -o out/cast

`run` appends one JSON line per (arm, prompt, seed) to `results.jsonl` and skips any
already recorded, so an interrupted run resumes where it stopped. Answers that met an
API error are retried on the next run rather than counted.
"""

import argparse
import copy
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from scenet import compile_ir, default_library, render
from scenet.errors import RuleViolationError, ScenetError
from scenet.frontends.common import normalise
from scenet.ir import PanelIR
from scenet.schema import panel_schema

#: Pinned so a rerun asks the same question. The recorded run (on #11) used this model,
#: listed as version `3.5-flash-lite-07-2026` at the time. `gemini-3.5-flash` was the first
#: choice, but its free tier allows 20 requests a day and a full run is 208.
MODEL = "gemini-3.5-flash-lite"
#: Gemini 3's documented default, and the setting its documentation advises keeping:
#: lower values are reported to cause looping. Greedy decoding would also turn each
#: prompt into one fixed draw, which is a worse estimate of a rate, not a better one.
TEMPERATURE = 1.0
SEEDS = (0,)
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

#: Attempts per call on a transient error (429, 500, 503), with exponential backoff.
ATTEMPTS = 6
BACKOFF_SECONDS = 4.0
TIMEOUT_SECONDS = 300


class ApiField(StrEnum):
    """The request field the schema is sent in."""

    JSON_SCHEMA = "responseJsonSchema"
    OPENAPI = "responseSchema"


class Base(StrEnum):
    """Which schema the arm starts from."""

    #: `PanelIR.model_json_schema()`: the IR as pydantic describes it.
    IR = "ir"
    #: `scenet.schema.panel_schema()`: the surface syntax, as `scenet schema` emits it.
    SURFACE = "surface"


class CastShape(StrEnum):
    """How `cast` is written."""

    MAPPING = "mapping"
    LIST = "list"


@dataclass(frozen=True)
class Arm:
    """One schema variant, sent the same prompts as every other."""

    api: ApiField
    base: Base
    cast: CastShape
    closed: bool = True

    @property
    def name(self) -> str:
        """A short, stable label for tables and records."""
        if self.api is ApiField.OPENAPI:
            # `additionalProperties` does not exist in that field, so open is all it can be.
            return f"openapi/{self.base}/{self.cast}"
        return f"json/{self.base}/{self.cast}/{'closed' if self.closed else 'open'}"


ARMS = (
    Arm(ApiField.JSON_SCHEMA, Base.IR, CastShape.MAPPING),
    Arm(ApiField.JSON_SCHEMA, Base.IR, CastShape.LIST),
    Arm(ApiField.JSON_SCHEMA, Base.IR, CastShape.MAPPING, closed=False),
    Arm(ApiField.JSON_SCHEMA, Base.IR, CastShape.LIST, closed=False),
    Arm(ApiField.OPENAPI, Base.IR, CastShape.MAPPING, closed=False),
    Arm(ApiField.OPENAPI, Base.IR, CastShape.LIST, closed=False),
    Arm(ApiField.JSON_SCHEMA, Base.SURFACE, CastShape.MAPPING),
    Arm(ApiField.JSON_SCHEMA, Base.SURFACE, CastShape.LIST),
)


@dataclass(frozen=True)
class Prompt:
    """One panel to ask for, in prose, as a person would describe it."""

    id: str
    brief: str


#: Drawn from the gallery, one or two per example, rewritten as the description a
#: person would give rather than the document that answers it. Three ask for one puppet
#: twice, which is where an actor id and a `reference` stop being the same word.
PROMPTS = (
    Prompt(
        "01-meeting",
        "Alice and Bob meet in the street. Alice, on the left, says "
        "hello; Bob answers that he is running late.",
    ),
    Prompt("02-close-up", "A close-up of Alice, looking scared, whispering: Did you hear that?"),
    Prompt(
        "03-low-angle",
        "Seen from a low angle, Bob stands with his hands on his hips and shouts: Nobody move!",
    ),
    Prompt(
        "04-balloon-kinds",
        "Alice speaks, Bob thinks, Alice whispers and Bob shouts: "
        "one line each, in that order, about a missing cat.",
    ),
    Prompt(
        "05-placement",
        "Alice stands alone in the middle of the panel. Her only "
        "line, 'Hello?', should sit in the top right corner.",
    ),
    Prompt(
        "06-reading-order",
        "Bob on the left and Alice on the right have a four-line "
        "argument about whose turn it is to cook, alternating, Bob first.",
    ),
    Prompt(
        "07-gaze", "Bob looks at Alice, who stares off to the side. Bob asks her what is wrong."
    ),
    Prompt(
        "08-ground",
        "Alice and Bob stand side by side on the same ground, seen full figure, saying nothing.",
    ),
    Prompt(
        "09-depth",
        "Bob stands in front of Alice, who peers out from behind him and says: Is it gone?",
    ),
    Prompt(
        "10-party",
        "A wide shot of a party with four guests, two played by Alice and "
        "two by Bob. One of the Bobs raises a toast: Cheers!",
    ),
    Prompt(
        "11-guards",
        "Two guards, both drawn as Bob, flank a door: the left one with "
        "arms crossed, the right one pointing and facing left. The left guard says: "
        "Halt.",
    ),
    Prompt(
        "12-docks",
        "Night at the docks. A caption reads 'Midnight. The docks.' Alice "
        "arrives and says: You said he would be here.",
    ),
    Prompt(
        "13-alley-rain",
        "An alley at dusk in the rain. Bob, soaked and sad, mutters: Of course it is raining.",
    ),
    Prompt(
        "14-long-speech",
        "Alice gives a long, rambling three-sentence explanation of "
        "why the train was late, while Bob looks bored.",
    ),
    Prompt(
        "15-wide-margin",
        "A very wide panel, 1600 by 600, with a generous margin. "
        "Alice at the far left and Bob at the far right shout at each other across "
        "the gap.",
    ),
    Prompt(
        "16-captions",
        "A medium shot of Alice with her arms crossed. A monologue "
        "caption says: I should have left town. Then a voice from off panel shouts, "
        "in a caption: Put that down!",
    ),
    Prompt("17-laughing", "Alice laughs at Bob, who is not amused and looks bored."),
    Prompt("18-face", "An extreme close-up of Bob's face. He is terrified."),
    Prompt("19-forest", "A forest at dawn, in fog. Alice points ahead and says: This way."),
    Prompt(
        "20-office",
        "An office in the daytime. Bob stands behind Alice, who tells him the report is due.",
    ),
    Prompt(
        "21-mountain",
        "A snowy mountain at night. Alice and Bob stand together on "
        "the same ground; Bob says he cannot feel his feet.",
    ),
    Prompt(
        "22-shore",
        "An ink-black editorial caption at the bottom reads 'Meanwhile...'. "
        "On the shore, Alice asks: Where is everyone?",
    ),
    Prompt("23-emanata", "Bob, sweating and swearing, shouts at Alice in anger. Alice is dizzy."),
    Prompt(
        "24-high-angle",
        "From a high angle, Alice sits alone in a room, sad, thinking: Why did I say that?",
    ),
    Prompt(
        "25-three",
        "Alice stands left of Bob, and Bob left of a second Alice. Both "
        "Alices look at Bob, who says: What?",
    ),
    Prompt(
        "26-cowboy",
        "A cowboy shot. Bob is on the left, Alice on the right; Alice "
        "whispers 'Don't turn around' and Bob looks surprised.",
    ),
)


def _instruction() -> str:
    library = default_library()
    lines = []
    for name in library.names():
        spec = library.get(name)
        poses = ", ".join(sorted(spec.poses))
        expressions = ", ".join(sorted(spec.expressions))
        lines.append(f"- {name}: poses {poses}; expressions {expressions}")
    characters = "\n".join(lines)
    return (
        "You write single comic panels in Scenet, a language that describes what a panel "
        "shows rather than where anything goes. Answer with one panel that conforms to "
        "the response schema; its descriptions explain the language.\n\n"
        "These are the only characters that can be drawn. Use these names as a cast "
        "member's reference, with only the poses and expressions listed for it:\n\n"
        f"{characters}\n\n"
        "One character may appear more than once in a panel, as two different people. "
        "Every actor named in staging or as a speaker must be in the cast."
    )


#: The same for every arm. Deliberately silent on the shape of `cast`.
SYSTEM_INSTRUCTION = _instruction()


# ---------------------------------------------------------------- schemas


def base_schema(base: Base) -> dict[str, Any]:
    """The schema an arm starts from, freshly built."""
    return PanelIR.model_json_schema() if base is Base.IR else panel_schema()


def flatten_cast(schema: dict[str, Any]) -> dict[str, Any]:
    """Rewrite `cast` from a mapping of id to member into a list of members with an id.

    The member's own definition is copied, not edited, with `id` added as the first and
    first-required property: everything else about a member is exactly as before.

    Args:
        schema: A panel schema whose `cast` is a mapping. Not modified.

    Returns:
        A copy in which `cast` is an array of `CastEntry`.
    """
    result = copy.deepcopy(schema)
    definitions: dict[str, Any] = result["$defs"]
    entry = copy.deepcopy(definitions["CastMember"])
    entry["title"] = "CastEntry"
    entry["properties"] = {
        "id": {
            "title": "Id",
            "type": "string",
            "description": "The actor id, used in staging and as a speaker.",
        },
        **entry["properties"],
    }
    entry["required"] = ["id", *entry.get("required", [])]
    definitions["CastEntry"] = entry
    result["properties"]["cast"] = {
        "title": "Cast",
        "type": "array",
        "items": {"$ref": "#/$defs/CastEntry"},
    }
    return result


def open_schema(node: Any) -> Any:  # noqa: ANN401 -- any JSON value
    """Remove every `additionalProperties: false`, keeping schema-valued ones."""
    if isinstance(node, dict):
        return {
            key: open_schema(value)
            for key, value in node.items()
            if not (key == "additionalProperties" and value is False)
        }
    if isinstance(node, list):
        return [open_schema(item) for item in node]
    return node


#: Keywords `responseSchema` refuses. `additionalProperties` among them is the point.
_OPENAPI_DROPPED = frozenset({"$schema", "$defs", "additionalProperties", "default"})


def to_openapi(node: Any, definitions: dict[str, Any]) -> Any:  # noqa: ANN401 -- any JSON value
    """Translate a pydantic JSON Schema into the OpenAPI subset `responseSchema` takes.

    `$ref` is inlined (the panel schema has no recursion), `const` becomes a one-value
    `enum`, a tuple's `prefixItems` becomes `items` (both of the IR's tuples are
    homogeneous), and `X | None` becomes `X` with `nullable`.

    One keyword is added: `propertyOrdering`, set to the order the model declares its
    fields in. It changes nothing a document may contain, but without it the API orders
    keys itself, and in trials the model then emitted `panel`, `setting` and `staging`
    and stopped -- no `camera`, no `cast`, no `script` -- under either cast shape. That
    would measure the field's key ordering rather than the shape of `cast`.
    """
    if isinstance(node, list):
        return [to_openapi(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        target = definitions[node["$ref"].rsplit("/", 1)[1]]
        sibling = {key: value for key, value in node.items() if key != "$ref"}
        return to_openapi({**target, **sibling}, definitions)

    result: dict[str, Any] = {}
    for key, value in node.items():
        if key in _OPENAPI_DROPPED:
            continue
        if key == "const":
            result["type"] = "string"
            result["enum"] = [value]
        elif key == "prefixItems":
            result["items"] = to_openapi(value[0], definitions)
        elif key == "properties":
            result[key] = {name: to_openapi(sub, definitions) for name, sub in value.items()}
        else:
            result[key] = to_openapi(value, definitions)
    if result.get("properties"):
        result["propertyOrdering"] = list(result["properties"])
    return _nullable(result)


def _nullable(result: dict[str, Any]) -> dict[str, Any]:
    """Fold a `null` branch of `anyOf` into `nullable`, which is how OpenAPI says it."""
    if "anyOf" not in result:
        return result
    branches = [branch for branch in result["anyOf"] if branch.get("type") != "null"]
    if len(branches) == len(result["anyOf"]):
        return result
    rest = {key: value for key, value in result.items() if key != "anyOf"}
    if len(branches) == 1:
        return {**branches[0], **rest, "nullable": True}
    return {**rest, "anyOf": branches, "nullable": True}


def schema_for(arm: Arm) -> dict[str, Any]:
    """The schema an arm sends, exactly as it goes into the request."""
    schema = base_schema(arm.base)
    if arm.cast is CastShape.LIST:
        schema = flatten_cast(schema)
    if not arm.closed:
        schema = open_schema(schema)
    if arm.api is ApiField.OPENAPI:
        schema = to_openapi(schema, schema["$defs"])
    return schema


def _openapi_as_json_schema(node: Any) -> Any:  # noqa: ANN401 -- any JSON value
    """Read an OpenAPI-subset schema back as JSON Schema, to check an answer against it."""
    if isinstance(node, list):
        return [_openapi_as_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    converted = {
        key: _openapi_as_json_schema(value) for key, value in node.items() if key != "nullable"
    }
    if node.get("properties") is not None:
        converted["properties"] = {
            name: _openapi_as_json_schema(sub) for name, sub in node["properties"].items()
        }
    if node.get("nullable"):
        return {"anyOf": [converted, {"type": "null"}]}
    return converted


def _conformance_schema(arm: Arm) -> dict[str, Any]:
    schema = schema_for(arm)
    return _openapi_as_json_schema(schema) if arm.api is ApiField.OPENAPI else schema


# ---------------------------------------------------------------- judging


class Stage(StrEnum):
    """How far an answer got. Each is charged to exactly one."""

    REJECTED = "schema_rejected"
    #: Quota or overload that outlasted every retry. Not the schema's fault, so it is
    #: left out of every rate and retried on the next run.
    UNAVAILABLE = "api_error"
    NO_OUTPUT = "no_output"
    JSON = "json_parse"
    #: Two members under one actor id. Possible in either shape: a repeated key in a
    #: JSON object, or a repeated `id` in a list. Neither is silently resolved.
    DUPLICATE = "duplicate_actor"
    VALIDATION = "ir_validation"
    COMPILE = "compile"
    COMPILED = "compiled"


#: Stages that mean the answer was a valid panel, whatever happened afterwards.
VALID_STAGES = frozenset({Stage.COMPILE.value, Stage.COMPILED.value})


@dataclass(frozen=True)
class Verdict:
    """Where an answer stopped, why, and whether it matched the schema it was sent."""

    stage: Stage
    detail: str = ""
    #: Whether the parsed answer validates against the schema that was sent. `None` when
    #: there was nothing to check. An answer can conform and still be invalid -- that
    #: is the half of validation no schema can do.
    conforms: bool | None = None


class DuplicateActorError(ValueError):
    """One actor id given to two members."""


def _no_repeats(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise DuplicateActorError(f"key {key!r} appears twice in one object")
        seen[key] = value
    return seen


def load_json(text: str) -> Any:  # noqa: ANN401 -- any JSON value
    """Parse JSON, refusing a repeated key instead of keeping the last one."""
    return json.loads(text, object_pairs_hook=_no_repeats)


def restore_cast(document: dict[str, Any]) -> dict[str, Any]:
    """Turn a flattened cast back into the mapping the language uses.

    Args:
        document: A parsed answer. Not modified.

    Returns:
        The document with `cast` as a mapping, in the order the members were listed.
        A mapping, or a missing cast, passes through as it is.

    Raises:
        DuplicateActorError: Two members share an id, or one has none.
    """
    cast = document.get("cast")
    if not isinstance(cast, list):
        return document
    restored: dict[str, Any] = {}
    for member in cast:
        if not isinstance(member, dict) or not isinstance(member.get("id"), str):
            raise DuplicateActorError(f"cast member has no id: {member!r}")
        actor = member["id"]
        if actor in restored:
            raise DuplicateActorError(f"actor id {actor!r} is given to two cast members")
        restored[actor] = {key: value for key, value in member.items() if key != "id"}
    return {**document, "cast": restored}


def _rule_of(exc: ValidationError) -> str:
    """The first error's rule, as `scenet check` would name it, then where and what."""
    error = exc.errors()[0]
    original = (error.get("ctx") or {}).get("error")
    rule = original.rule if isinstance(original, RuleViolationError) else str(error["type"])
    location = ".".join(str(part) for part in error["loc"]) or "<root>"
    return f"{rule}: {location}: {error['msg'].removeprefix('Value error, ')}"


def _load_panel(document: Any, arm: Arm) -> PanelIR:  # noqa: ANN401 -- any JSON value
    """Validate exactly as the arm's schema implies the answer will be read.

    A flattened cast is first read back into a mapping. Then an IR-shaped answer goes
    straight into `PanelIR`, and a surface-shaped answer goes through `normalise`
    first, which is what the YAML frontend does after parsing -- the same two calls as
    `yaml_front._validate_panel`, without the message rewriting that would lose the rule.

    Raises:
        DuplicateActorError: Two cast members share an actor id.
        ScenetError: The answer is not an object, or the frontend refused it.
        ValidationError: The IR refused it.
    """
    if not isinstance(document, dict):
        raise ScenetError(f"expected an object at the top level, got {type(document).__name__}")
    document = restore_cast(document)
    if arm.base is Base.SURFACE:
        document = normalise(document)
    return PanelIR.model_validate(document)


def _validate_and_compile(document: Any, arm: Arm) -> tuple[Stage, str]:  # noqa: ANN401
    """Carry a parsed answer as far as it goes: validation, compile, render."""
    try:
        panel = _load_panel(document, arm)
    except DuplicateActorError as exc:
        return Stage.DUPLICATE, str(exc)
    except ValidationError as exc:
        return Stage.VALIDATION, _rule_of(exc)
    except ScenetError as exc:
        return Stage.VALIDATION, f"{getattr(exc, 'rule', None) or 'syntax'}: {exc}"

    # Broad on purpose: a crash on IR that validated is a finding too, not a reason to stop.
    try:
        render(compile_ir(panel).core)
    except Exception as exc:
        return Stage.COMPILE, f"{type(exc).__name__}: {exc}"
    return Stage.COMPILED, ""


def judge(text: str, arm: Arm) -> Verdict:
    """Decide how far one answer gets, from JSON parsing to a rendered SVG.

    Args:
        text: The model's answer, verbatim.
        arm: The arm it was produced under, which decides how it is read.

    Returns:
        The stage it stopped at, with the reason.
    """
    try:
        document = load_json(text)
    except DuplicateActorError as exc:
        return Verdict(Stage.DUPLICATE, str(exc))
    except json.JSONDecodeError as exc:
        return Verdict(Stage.JSON, f"{exc.msg} at {exc.pos} of {len(text)}")

    conforms = Draft202012Validator(_conformance_schema(arm)).is_valid(document)
    stage, detail = _validate_and_compile(document, arm)
    return Verdict(stage, detail, conforms)


# ---------------------------------------------------------------- calling the API


def request_body(arm: Arm, prompt: Prompt, *, seed: int) -> dict[str, Any]:
    """The full request for one answer. Everything a rerun needs is in here."""
    return {
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": prompt.brief}]}],
        "generationConfig": {
            "temperature": TEMPERATURE,
            "seed": seed,
            "responseMimeType": "application/json",
            arm.api.value: schema_for(arm),
        },
    }


@dataclass
class Reply:
    """What came back from one call, after retries."""

    status: int
    body: dict[str, Any] = field(default_factory=dict)
    attempts: int = 1


def _post(model: str, body: dict[str, Any]) -> Reply:
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        headers["x-goog-api-key"] = key
    data = json.dumps(body).encode("utf-8")
    url = ENDPOINT.format(model=model)
    for attempt in range(1, ATTEMPTS + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")  # noqa: S310 -- fixed https URL
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
                return Reply(response.status, json.load(response), attempt)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.load(exc)
            except json.JSONDecodeError:
                payload = {}
            if exc.code not in (429, 500, 503) or attempt == ATTEMPTS:
                return Reply(exc.code, payload, attempt)
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == ATTEMPTS:
                return Reply(0, {"error": {"message": str(exc)}}, attempt)
        time.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
    raise AssertionError("unreachable")  # pragma: no cover


def _record(arm: Arm, prompt: Prompt, seed: int, model: str, reply: Reply) -> dict[str, Any]:
    record: dict[str, Any] = {
        "arm": arm.name,
        "prompt": prompt.id,
        "seed": seed,
        "model": model,
        "temperature": TEMPERATURE,
        "attempts": reply.attempts,
        "http_status": reply.status,
    }
    if reply.status != 200:
        error = reply.body.get("error", {})
        message = str(error.get("message", ""))[:600]
        rejected = reply.status == 400 and error.get("status") == "INVALID_ARGUMENT"
        stage = Stage.REJECTED if rejected else Stage.UNAVAILABLE
        return {**record, "stage": stage.value, "detail": message}

    record["model_version"] = reply.body.get("modelVersion")
    record["usage"] = reply.body.get("usageMetadata")
    candidates = reply.body.get("candidates") or []
    if not candidates:
        feedback = json.dumps(reply.body.get("promptFeedback", {}))
        return {**record, "stage": Stage.NO_OUTPUT.value, "detail": feedback}
    candidate = candidates[0]
    record["finish_reason"] = candidate.get("finishReason")
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
    if not text:
        return {**record, "stage": Stage.NO_OUTPUT.value, "detail": str(candidate)[:600]}

    verdict = judge(text, arm)
    return {
        **record,
        "stage": verdict.stage.value,
        "detail": verdict.detail[:600],
        "conforms": verdict.conforms,
        "text": text,
    }


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _key(record: dict[str, Any]) -> tuple[str, str, int]:
    return (record["arm"], record["prompt"], record["seed"])


def run(
    out: Path,
    *,
    model: str,
    arms: Iterable[Arm],
    prompts: Iterable[Prompt],
    seeds: Iterable[int],
    workers: int,
) -> None:
    """Ask for every (arm, prompt, seed) not already recorded, appending as they finish."""
    out.mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    done = {
        _key(record)
        for record in _read_records(results)
        if record["stage"] != Stage.UNAVAILABLE.value
    }
    # Prompt-major, so every arm sees the API in the same conditions at about the same
    # time; a burst of overload then lands on all arms rather than on one.
    jobs = [
        (arm, prompt, seed)
        for seed in seeds
        for prompt in prompts
        for arm in arms
        if (arm.name, prompt.id, seed) not in done
    ]
    print(f"{len(jobs)} calls to make against {model}", file=sys.stderr)
    lock = threading.Lock()

    def one(job: tuple[Arm, Prompt, int]) -> None:
        arm, prompt, seed = job
        reply = _post(model, request_body(arm, prompt, seed=seed))
        record = _record(arm, prompt, seed, model, reply)
        with lock, results.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            print(f"{arm.name:28} {prompt.id:18} {record['stage']}", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(one, jobs):
            pass


# ---------------------------------------------------------------- reporting


@dataclass
class Row:
    """One arm's totals."""

    arm: str
    attempted: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    valid: int = 0
    compiled: int = 0
    conforming: int = 0


def latest(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The last record for each (arm, prompt, seed), so a retried call counts once."""
    kept: dict[tuple[str, str, int], dict[str, Any]] = {}
    for record in records:
        kept[_key(record)] = record
    return [kept[key] for key in sorted(kept)]


def tally(records: Iterable[dict[str, Any]]) -> list[Row]:
    """Per-arm counts. API errors are left out of `attempted`, and so out of every rate."""
    rows: dict[str, Row] = {}
    for record in latest(records):
        row = rows.setdefault(record["arm"], Row(record["arm"]))
        stage = record["stage"]
        row.counts[stage] = row.counts.get(stage, 0) + 1
        if stage == Stage.UNAVAILABLE.value:
            continue
        row.attempted += 1
        row.valid += stage in VALID_STAGES
        row.compiled += stage == Stage.COMPILED.value
        row.conforming += record.get("conforms") is True
    return [rows[name] for name in sorted(rows)]


def mcnemar(only_first: int, only_second: int) -> float:
    """Exact two-sided McNemar test on the discordant pairs of a paired comparison.

    Every arm answers the same prompts, so arms are compared prompt by prompt: only the
    prompts on which exactly one arm succeeded carry information about which is better.

    Args:
        only_first: Prompts where only the first arm succeeded.
        only_second: Prompts where only the second arm succeeded.

    Returns:
        The p-value, capped at 1.
    """
    total = only_first + only_second
    if total == 0:
        return 1.0
    tail = sum(math.comb(total, k) for k in range(min(only_first, only_second) + 1))
    return min(1.0, 2 * tail / 2**total)


def discordant(records: Iterable[dict[str, Any]], first: str, second: str) -> tuple[int, int]:
    """Count the prompts on which exactly one of two arms compiled.

    Pairs where either arm met an API error are skipped: they say nothing about either
    schema.
    """
    by_key: dict[tuple[str, int], dict[str, str]] = {}
    for record in latest(records):
        by_key.setdefault((record["prompt"], record["seed"]), {})[record["arm"]] = record["stage"]
    only_first = only_second = 0
    for stages in by_key.values():
        if first not in stages or second not in stages:
            continue
        if Stage.UNAVAILABLE.value in (stages[first], stages[second]):
            continue
        a = stages[first] == Stage.COMPILED.value
        b = stages[second] == Stage.COMPILED.value
        only_first += a and not b
        only_second += b and not a
    return only_first, only_second


#: Columns of the report, in pipeline order.
_COLUMNS = (
    Stage.REJECTED,
    Stage.NO_OUTPUT,
    Stage.JSON,
    Stage.DUPLICATE,
    Stage.VALIDATION,
    Stage.COMPILE,
    Stage.COMPILED,
)

#: The comparisons the experiment exists to make.
_PAIRS = (
    ("json/ir/mapping/closed", "json/ir/list/closed"),
    ("json/ir/mapping/open", "json/ir/list/open"),
    ("json/ir/mapping/closed", "json/ir/mapping/open"),
    ("json/ir/list/closed", "json/ir/list/open"),
    ("openapi/ir/mapping", "openapi/ir/list"),
    ("json/surface/mapping/closed", "json/surface/list/closed"),
)


def _percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "-"


def report(records: list[dict[str, Any]]) -> Iterator[str]:
    """The results as Markdown: one row per arm, then the paired comparisons."""
    rows = tally(records)
    header = ["arm", "n", *(stage.value for stage in _COLUMNS), "valid", "compiled", "conforms"]
    yield "| " + " | ".join(header) + " |"
    yield "|" + "|".join("---" for _ in header) + "|"
    for row in rows:
        cells = [
            f"`{row.arm}`",
            str(row.attempted),
            *(str(row.counts.get(stage.value, 0)) for stage in _COLUMNS),
            f"{row.valid}/{row.attempted} ({_percent(row.valid, row.attempted)})",
            f"{row.compiled}/{row.attempted} ({_percent(row.compiled, row.attempted)})",
            f"{row.conforming}/{row.attempted}",
        ]
        yield "| " + " | ".join(cells) + " |"
    unavailable = sum(row.counts.get(Stage.UNAVAILABLE.value, 0) for row in rows)
    if unavailable:
        yield ""
        yield f"{unavailable} calls met an API error after every retry and are not counted."

    names = {row.arm for row in rows}
    yield ""
    yield "| compiled: A vs B | only A | only B | McNemar exact p |"
    yield "|---|---|---|---|"
    for first, second in _PAIRS:
        if first in names and second in names:
            a, b = discordant(records, first, second)
            yield f"| `{first}` vs `{second}` | {a} | {b} | {mcnemar(a, b):.3f} |"

    failures: dict[tuple[str, str], int] = {}
    for record in latest(records):
        if record["stage"] in (Stage.VALIDATION.value, Stage.COMPILE.value):
            reason = record["detail"].split(":", 1)[0]
            failures[(record["arm"], reason)] = failures.get((record["arm"], reason), 0) + 1
    if failures:
        yield ""
        yield "| arm | failure | count |"
        yield "|---|---|---|"
        for (arm, reason), count in sorted(failures.items()):
            yield f"| `{arm}` | `{reason}` | {count} |"


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "report"):
        command = commands.add_parser(name)
        command.add_argument("-o", "--out", type=Path, required=True, help="results directory")
    runner = commands.choices["run"]
    runner.add_argument("--model", default=MODEL)
    runner.add_argument("--arms", nargs="*", help="arm names to run (default: all)")
    runner.add_argument("--prompts", type=int, default=len(PROMPTS), help="first N prompts")
    runner.add_argument("--seeds", type=int, nargs="*", default=list(SEEDS))
    runner.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    if args.command == "run":
        arms = [arm for arm in ARMS if not args.arms or arm.name in args.arms]
        run(
            args.out,
            model=args.model,
            arms=arms,
            prompts=PROMPTS[: args.prompts],
            seeds=args.seeds,
            workers=args.workers,
        )
    for line in report(_read_records(args.out / "results.jsonl")):
        print(line)


if __name__ == "__main__":
    main()

"""The JSON Schema for Scenet documents, as people write them.

The pydantic models in :mod:`scenet.ir <scenet.ir>` are the language's real definition,
and `PanelIR.model_json_schema()` describes them faithfully. **It does not describe what
anybody types.** The YAML frontend accepts conveniences that
:func:`normalise <scenet.frontends.common.normalise>` and
:func:`merge <scenet.compose.merge>` remove before the models see the document:

- staging written as a sentence, `alice left_of bob`;
- script entries tagged by verb, `- say: {by: alice, text: ...}`;
- a setting that names a `place` instead of listing masses;
- in a scene, panels that state only what differs from what they inherit.

Publishing the IR's schema made an editor flag every one of those as an error -- 21 of
the 22 gallery documents, on lines that compiled. So the published schema starts from
the IR's and puts each convenience back, next to a note of the code it mirrors. Every
field, enum and docstring still comes from the models; only the shape changes.

Example:
    >>> from scenet.schema import panel_schema
    >>> schema = panel_schema()
    >>> sorted(schema["properties"]["script"]["items"]["anyOf"][0]["properties"])
    ['say']
"""

import inspect
from typing import Any

from scenet.ir import PanelIR, Predicate
from scenet.places import Place

__all__ = ["panel_schema", "scene_schema"]

DIALECT = "https://json-schema.org/draft/2020-12/schema"


def panel_schema() -> dict[str, Any]:
    """The schema for a single-panel document.

    Returns:
        A JSON Schema (draft 2020-12) that accepts exactly the surface syntax a
        `.panel.yaml` file is written in.
    """
    schema = PanelIR.model_json_schema()
    definitions: dict[str, Any] = schema["$defs"]
    _accept_staging_sentences(definitions)
    _accept_verb_tagged_script(schema, definitions)
    _accept_named_places(definitions)
    schema["$schema"] = DIALECT
    schema["title"] = "Scenet panel"
    return schema


def scene_schema() -> dict[str, Any]:
    """The schema for a multi-panel document.

    Built from the panel schema rather than declared separately, so the two can never
    describe different languages. A scene allows the same keys as a panel -- there they
    act as defaults every panel inherits -- plus `panels`, whose members may
    additionally carry `over`.

    Returns:
        A JSON Schema (draft 2020-12) for a `.scene.yaml` file.
    """
    panel = panel_schema()
    definitions: dict[str, Any] = panel.pop("$defs")
    properties = {
        key: _inheritable(value, definitions) for key, value in panel["properties"].items()
    }

    member = {key: value for key, value in panel.items() if key not in ("title", "$schema")}
    member["properties"] = {
        **properties,
        "over": {
            "type": "string",
            "description": (
                "Name of a panel to inherit from. Only the differences need stating: "
                "mappings merge recursively and lists replace."
            ),
        },
    }

    return {
        "$schema": DIALECT,
        "title": "Scenet scene",
        "$defs": definitions,
        "type": "object",
        "properties": {
            **properties,
            "panels": {
                "type": "object",
                "description": (
                    "Panels in reading order. Each may inherit from another with `over`."
                ),
                "additionalProperties": member,
            },
        },
        "additionalProperties": False,
    }


def _accept_staging_sentences(definitions: dict[str, Any]) -> None:
    """Mirror `parse_relation`: a staging entry may be `subject predicate object`.

    The pattern is built from :class:`Predicate <scenet.ir.Predicate>`, so a predicate
    added to the language is accepted here without anyone remembering to. The mapping
    form stays valid, because the frontend passes a mapping through untouched.
    """
    relation: dict[str, Any] = definitions["Relation"]
    predicates = [member.value for member in Predicate]
    sentence = {
        "type": "string",
        "pattern": rf"^\s*\S+\s+({'|'.join(predicates)})\s+\S+\s*$",
        # Not a JSON Schema keyword. VS Code and monaco-yaml show it in place of the
        # raw regular expression, which tells nobody what went wrong.
        "patternErrorMessage": (
            f"Write 'subject predicate object', where the predicate is one of: "
            f"{', '.join(predicates)}"
        ),
        "description": (
            "A staging sentence, `subject predicate object` -- for example "
            "`alice left_of bob`. Predicates: " + ", ".join(predicates) + "."
        ),
    }
    mapping = {key: value for key, value in relation.items() if key not in ("title", "description")}
    definitions["Relation"] = {
        "title": relation["title"],
        "description": relation.get("description", ""),
        "anyOf": [sentence, mapping],
    }


def _accept_verb_tagged_script(schema: dict[str, Any], definitions: dict[str, Any]) -> None:
    """Mirror `normalise`: each script entry is a one-key mapping naming its verb.

    The frontend moves the key into the payload as `verb`, which is where the event
    models expect it. So here the reverse: the verb comes out of each event and becomes
    the key that wraps it. The verbs are read from the models' own `verb` constants.
    """
    script: dict[str, Any] = schema["properties"]["script"]
    branches: list[dict[str, Any]] = []
    for branch in script["items"]["anyOf"]:
        name = branch["$ref"].rsplit("/", 1)[1]
        event: dict[str, Any] = definitions[name]
        verb = event["properties"].pop("verb")["const"]
        if "required" in event:
            event["required"] = [field for field in event["required"] if field != "verb"]
        branches.append(
            {
                "type": "object",
                "properties": {verb: {"$ref": f"#/$defs/{name}"}},
                "required": [verb],
                "additionalProperties": False,
            }
        )
    script["items"] = {"anyOf": branches}


def _accept_named_places(definitions: dict[str, Any]) -> None:
    """Mirror `expand_place`: a setting may name a place, but not alongside masses."""
    definitions["Place"] = {
        "title": "Place",
        "description": inspect.cleandoc(Place.__doc__ or ""),
        "type": "string",
        "enum": [place.value for place in Place],
    }
    setting: dict[str, Any] = definitions["SettingSpec"]
    setting["properties"]["place"] = {
        "$ref": "#/$defs/Place",
        "description": (
            "A named place, which stands for the list of masses it expands into. "
            "Write this or `masses`, not both."
        ),
    }
    setting["not"] = {"required": ["place", "masses"]}


def _inheritable(node: dict[str, Any], definitions: dict[str, Any]) -> dict[str, Any]:
    """Loosen a scene property, which may be stated only in part.

    :func:`merge <scenet.compose.merge>` deep-merges mappings and replaces lists. So
    anything reached through mapping keys may leave fields to be inherited -- an
    override can change one actor's pose without restating its `reference` -- while
    anything inside a list must still be whole. That is why `items` is never descended.
    """
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[1]
        partial = _partial_definition(name, definitions)
        return node if partial == name else {**node, "$ref": f"#/$defs/{partial}"}

    loosened = {key: value for key, value in node.items() if key != "required"}
    if isinstance(node.get("additionalProperties"), dict):
        loosened["additionalProperties"] = _inheritable(node["additionalProperties"], definitions)
    if "properties" in node:
        loosened["properties"] = {
            key: _inheritable(value, definitions) for key, value in node["properties"].items()
        }
    for combinator in ("anyOf", "oneOf", "allOf"):
        if combinator in node:
            loosened[combinator] = [
                _inheritable(branch, definitions) for branch in node[combinator]
            ]
    return loosened


def _partial_definition(name: str, definitions: dict[str, Any]) -> str:
    """The name of a copy of `name` with nothing required, adding it if it differs."""
    definition: dict[str, Any] = definitions[name]
    loosened = _inheritable(definition, definitions)
    if loosened == definition:
        return name
    partial = f"Partial{name}"
    description = definition.get("description", "")
    loosened["description"] = (
        f"{description}\n\n" if description else ""
    ) + "In a scene any of these may be inherited, so none is required here."
    definitions[partial] = loosened
    return partial

# The language

The intermediate representation: a validated semantic scene graph, and the real
definition of the language. Nothing here carries a coordinate.

## `scenet.ir`

```{automodule} scenet.ir
```

## `scenet.places`

The named-place library. A preset expands into a mass list an author could have written
themselves, which is what keeps it a library rather than a second, opaque format -- and
the expansion happens in the frontend, so nothing downstream ever sees a `place`.

```{automodule} scenet.places
```

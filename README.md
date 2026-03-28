# fdo-resolver

Resolve RO-Crate FAIR Digital Object inputs for scientific workflows.

Given a [Workflow RO-Crate](https://w3id.org/workflowhub/workflow-ro-crate/1.0) that declares its expected inputs as `FormalParameter` entities, `fdo-resolver` scans a directory of data RO-Crates and matches them to the workflow's input slots by `encodingFormat`, `additionalType`, `name`, and `variableMeasured`.

## Installation

```bash
pip install fdo-resolver
```

## Usage

### Basic: resolve data crates to workflow inputs

```python
from fdo_resolver import FDOResolver

# Load input slots from a Workflow RO-Crate
resolver = FDOResolver.from_workflow_crate("path/to/workflow-rocrate/")

# Resolve data crates against the workflow profile
result = resolver.resolve("path/to/input-data/")

print(result.is_complete)  # True if all required inputs matched
print(result.paths)        # {param_name: Path(...), ...}
print(result.summary())    # Human-readable summary
```

### Variable-level matching with I-ADOPT

When input datasets describe their columns via `variableMeasured` (using [schema.org PropertyValue](https://schema.org/PropertyValue) with `propertyID` pointing to semantic identifiers like [I-ADOPT](https://i-adopt.github.io/) nanopublications), the resolver can match columns between workflow expectations and data offerings.

**Workflow RO-Crate** declares expected variables:

```json
{
  "@id": "#param-buildings",
  "@type": "FormalParameter",
  "name": "buildings",
  "encodingFormat": "application/flatgeobuf",
  "variableMeasured": [
    {"@id": "#expected-elderly-singles"}
  ]
}
```
```json
{
  "@id": "#expected-elderly-singles",
  "@type": "PropertyValue",
  "name": "elderly_singles",
  "propertyID": "https://w3id.org/np/RA...",
  "additionalType": "sensitivity_indicator"
}
```

**Data RO-Crate** describes its columns:

```json
{
  "@id": "buildings.fgb",
  "@type": "File",
  "encodingFormat": "application/flatgeobuf",
  "variableMeasured": [
    {"@id": "#var-es"}
  ]
}
```
```json
{
  "@id": "#var-es",
  "@type": "PropertyValue",
  "name": "ES",
  "propertyID": "https://w3id.org/np/RA..."
}
```

**Resolve and get column mappings:**

```python
result = resolver.resolve("path/to/input-data/")

# Get the column mapping for the buildings input
binding = result.bindings["buildings"]
print(binding.column_mapping)
# {"elderly_singles": "ES"}
# workflow expects "elderly_singles" → data has it as column "ES"
```

The `propertyID` (e.g. an I-ADOPT nanopublication URI) is the semantic key that connects the workflow's expected variable to the data's actual column name. This allows different cities to use different column names while the workflow remains generic.

### Programmatic parameter definitions

```python
resolver = FDOResolver.from_parameters([
    {
        "name": "buildings",
        "encoding_format": "application/flatgeobuf",
        "variables_measured": [
            {
                "name": "elderly_singles",
                "property_id": "https://w3id.org/np/RA...",
                "role": "sensitivity_indicator",
            },
        ],
    },
    {
        "name": "flood_levels",
        "encoding_format": "application/geo+json",
        "additional_type": "https://example.org/FloodLevelCollection",
    },
])

result = resolver.resolve("path/to/input-data/")
```

### Creating output Workflow Run Crates

```python
resolver.create_run_crate(
    "path/to/output/",
    name="Hamburg Flood Risk Results",
    description="PFRMA and PFRWB risk indices",
    bindings=result,  # records input provenance
    output_files={"Risk layer": Path("output/risk.fgb")},
)
```

## How matching works

The resolver scores each data entity against each workflow parameter:

1. **`encodingFormat`** — file format match (strongest signal)
2. **`additionalType`** — semantic type match (e.g. `FloodLevelCollection`)
3. **`variableMeasured`** — overlap of `propertyID` URIs between expected and actual variables
4. **`name`** — name-based match (weakest signal)

Scores are combined and the best matches are assigned greedily.

## License

MIT

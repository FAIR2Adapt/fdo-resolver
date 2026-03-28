"""
FDOResolver – Profile-based RO-Crate input resolution for scientific workflows.

Uses the rocrate library to read Workflow RO-Crate profiles, discover
FormalParameter input slots, and match incoming data RO-Crates to those
slots by encodingFormat, additionalType, and name.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

from rocrate.rocrate import ROCrate

# Common format extensions for fallback guessing
FORMAT_EXTENSIONS = {
    ".geojson": "application/geo+json",
    ".gpkg": "application/geopackage+sqlite3",
    ".gdb": "application/x-filegdb",
    ".shp": "application/x-shapefile",
    ".fgb": "application/flatgeobuf",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".csv": "text/csv",
    ".json": "application/json",
    ".yaml": "application/x-yaml",
    ".yml": "application/x-yaml",
    ".zip": "application/zip",
    ".nc": "application/x-netcdf",
    ".parquet": "application/x-parquet",
}


@dataclass
class VariableDescription:
    """A measured variable described using schema.org PropertyValue / I-ADOPT.

    Maps a column name in a dataset to a semantic identifier (e.g. an
    I-ADOPT nanopublication URI) and an optional role within the workflow
    (e.g. "sensitivity_indicator", "coping_indicator").
    """

    name: str  # column name in the data (e.g. "ES")
    property_id: str = ""  # I-ADOPT nanopub URI or other semantic ID
    description: str = ""
    role: str = ""  # workflow role (e.g. "sensitivity_indicator")


@dataclass
class FormalParameter:
    """A workflow input/output slot declared in a Workflow RO-Crate."""

    id: str
    name: str
    additional_type: str = ""
    encoding_formats: List[str] = field(default_factory=list)
    value_required: bool = True
    default_value: Optional[str] = None
    description: str = ""
    conforms_to: str = ""
    variables_measured: List[VariableDescription] = field(default_factory=list)

    @property
    def encoding_format(self) -> str:
        """Primary encoding format (first in list), for convenience."""
        return self.encoding_formats[0] if self.encoding_formats else ""

    def matches(self, data_entity: "DataEntity") -> float:
        """Score how well a data entity matches this parameter (0.0–1.0)."""
        score = 0.0
        checks = 0

        # encodingFormat match (strongest signal)
        if self.encoding_formats and data_entity.encoding_format:
            checks += 1
            if data_entity.encoding_format in self.encoding_formats:
                score += 1.0
            elif any(
                _formats_compatible(fmt, data_entity.encoding_format)
                for fmt in self.encoding_formats
            ):
                score += 0.8

        # additionalType match (strongest semantic signal)
        if self.additional_type:
            checks += 1
            if data_entity.additional_type:
                if self.additional_type == data_entity.additional_type:
                    score += 1.0
                else:
                    # Wrong type is a strong negative signal
                    score -= 0.5
            # else: parameter expects a type but entity has none → 0 (no match)

        # variableMeasured match (semantic column matching)
        if self.variables_measured and data_entity.variables_measured:
            checks += 1
            param_ids = {v.property_id for v in self.variables_measured if v.property_id}
            entity_ids = {v.property_id for v in data_entity.variables_measured if v.property_id}
            if param_ids and entity_ids:
                overlap = len(param_ids & entity_ids)
                score += overlap / len(param_ids) if param_ids else 0.0

        # Name-based match (weakest signal)
        if self.name and data_entity.name:
            checks += 1
            if self.name.lower() == data_entity.name.lower():
                score += 1.0
            elif self.name.lower() in data_entity.name.lower():
                score += 0.5
            elif data_entity.name.lower() in self.name.lower():
                score += 0.3

        return score / checks if checks > 0 else 0.0


@dataclass
class DataEntity:
    """A data file or dataset found in an incoming RO-Crate."""

    id: str
    name: str
    path: Path
    entity_type: str = "File"
    encoding_format: str = ""
    additional_type: str = ""
    description: str = ""
    crate_dir: Optional[Path] = None
    variables_measured: List[VariableDescription] = field(default_factory=list)


@dataclass
class Binding:
    """A resolved match between a FormalParameter and a DataEntity."""

    parameter: FormalParameter
    entity: DataEntity
    score: float

    @property
    def path(self) -> Path:
        return self.entity.path

    @property
    def column_mapping(self) -> Dict[str, str]:
        """Map workflow variable names to data column names via propertyID.

        Returns a dict like {"elderly_singles": "ES"} where the key is
        the workflow's variable name and the value is the data's column name.
        Matching is done by I-ADOPT propertyID (nanopub URI).
        """
        if not self.parameter.variables_measured or not self.entity.variables_measured:
            return {}

        param_by_id = {
            v.property_id: v.name
            for v in self.parameter.variables_measured
            if v.property_id
        }
        entity_by_id = {
            v.property_id: v.name
            for v in self.entity.variables_measured
            if v.property_id
        }

        mapping = {}
        for pid, param_name in param_by_id.items():
            if pid in entity_by_id:
                mapping[param_name] = entity_by_id[pid]

        return mapping


@dataclass
class ResolvedBindings:
    """Result of resolving data crates against a workflow profile."""

    bindings: Dict[str, Binding] = field(default_factory=dict)
    unmatched_params: List[FormalParameter] = field(default_factory=list)
    unmatched_entities: List[DataEntity] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """True if all required parameters have been matched."""
        return not any(p.value_required for p in self.unmatched_params)

    @property
    def paths(self) -> Dict[str, Path]:
        """Mapping of parameter name -> resolved file path."""
        return {name: b.path for name, b in self.bindings.items()}

    def summary(self) -> str:
        lines = []
        for name, b in self.bindings.items():
            lines.append(f"  {name} -> {b.entity.path.name} (score={b.score:.2f})")
        if self.unmatched_params:
            req = [p.name for p in self.unmatched_params if p.value_required]
            opt = [p.name for p in self.unmatched_params if not p.value_required]
            if req:
                lines.append(f"  MISSING (required): {', '.join(req)}")
            if opt:
                lines.append(f"  MISSING (optional): {', '.join(opt)}")
        if self.unmatched_entities:
            names = [e.name or e.id for e in self.unmatched_entities]
            lines.append(f"  Unmatched data: {', '.join(names)}")
        return "\n".join(lines)


class FDOResolver:
    """
    Resolve RO-Crate FAIR Digital Object inputs for a workflow.

    Reads a Workflow RO-Crate (using the rocrate library) to discover the
    expected input parameters (FormalParameter), then matches incoming data
    RO-Crates to those slots.

    Parameters
    ----------
    parameters : list of FormalParameter
        The input slots the workflow expects.
    extra_formats : dict, optional
        Additional extension -> MIME type mappings for format guessing.
    """

    def __init__(
        self,
        parameters: Optional[List[FormalParameter]] = None,
        extra_formats: Optional[Dict[str, str]] = None,
    ):
        self.parameters: List[FormalParameter] = parameters or []
        self.formats = {**FORMAT_EXTENSIONS, **(extra_formats or {})}

    # ── Constructors ──

    @classmethod
    def from_workflow_crate(
        cls,
        crate_dir: Union[str, Path],
        extra_formats: Optional[Dict[str, str]] = None,
    ) -> "FDOResolver":
        """
        Create a resolver from a Workflow RO-Crate directory.

        Reads the crate using the rocrate library, finds the
        ComputationalWorkflow mainEntity, and extracts its
        FormalParameter inputs (Workflow RO-Crate profile).
        """
        crate_dir = Path(crate_dir)
        if not (crate_dir / "ro-crate-metadata.json").exists():
            raise FileNotFoundError(f"No ro-crate-metadata.json in {crate_dir}")

        crate = ROCrate(str(crate_dir))

        # Find the workflow via mainEntity (Workflow RO-Crate profile)
        workflow = crate.mainEntity
        if workflow is None:
            # Fallback: search by type
            workflows = crate.get_by_type("ComputationalWorkflow")
            if not workflows:
                raise ValueError(
                    f"No ComputationalWorkflow entity found in {crate_dir}"
                )
            workflow = workflows[0]

        # Extract FormalParameter inputs
        params = []
        inputs = workflow.get("input")
        if inputs is not None:
            if not isinstance(inputs, list):
                inputs = [inputs]
            for fp in inputs:
                params.append(_entity_to_formal_parameter(fp))

        return cls(parameters=params, extra_formats=extra_formats)

    @classmethod
    def from_parameters(
        cls,
        params: List[Dict],
        extra_formats: Optional[Dict[str, str]] = None,
    ) -> "FDOResolver":
        """
        Create a resolver from a list of parameter dicts.

        Each dict should have keys: name, encoding_format (str or list),
        additional_type, value_required, description.
        """
        parameters = []
        for i, p in enumerate(params):
            fmt = p.get("encoding_format", "")
            if isinstance(fmt, str):
                fmts = [fmt] if fmt else []
            else:
                fmts = list(fmt)

            # Parse variables_measured from dict format
            vars_raw = p.get("variables_measured", [])
            variables = []
            for v in vars_raw:
                if isinstance(v, str):
                    variables.append(VariableDescription(name=v))
                elif isinstance(v, dict):
                    variables.append(
                        VariableDescription(
                            name=v.get("name", ""),
                            property_id=v.get("property_id", v.get("propertyID", "")),
                            description=v.get("description", ""),
                            role=v.get("role", v.get("additionalType", "")),
                        )
                    )

            parameters.append(
                FormalParameter(
                    id=p.get("id", f"#param-{i}"),
                    name=p["name"],
                    encoding_formats=fmts,
                    additional_type=p.get("additional_type", ""),
                    value_required=p.get("value_required", True),
                    default_value=p.get("default_value"),
                    description=p.get("description", ""),
                    variables_measured=variables,
                )
            )
        return cls(parameters=parameters, extra_formats=extra_formats)

    # ── Core methods ──

    def resolve(self, input_dir: Union[str, Path]) -> ResolvedBindings:
        """
        Scan input_dir for RO-Crate directories and match to parameters.

        Parameters
        ----------
        input_dir : str or Path
            Directory containing one or more RO-Crate subdirectories,
            each with ro-crate-metadata.json and data files.

        Returns
        -------
        ResolvedBindings
            The resolved parameter->data mappings and any unmatched items.
        """
        input_dir = Path(input_dir)
        entities = self._discover_data_entities(input_dir)

        return self._match(entities)

    def read_crate(self, crate_dir: Union[str, Path]) -> List[DataEntity]:
        """
        Read a single RO-Crate and return its data entities.

        Uses the rocrate library to parse the crate. The root dataset
        is included as a matchable entity when it has additionalType set
        (i.e. the crate itself represents a typed FDO collection).

        Parameters
        ----------
        crate_dir : str or Path
            Path to a directory containing ro-crate-metadata.json.

        Returns
        -------
        list of DataEntity
        """
        crate_dir = Path(crate_dir)
        if not (crate_dir / "ro-crate-metadata.json").exists():
            return []

        crate = ROCrate(str(crate_dir))
        entities = []

        # Root dataset as FDO: when the crate itself has additionalType,
        # it represents a typed collection (e.g. a set of flood level files)
        root = crate.root_dataset
        root_additional = _get_prop_str(root, "additionalType")
        if root_additional:
            entities.append(
                DataEntity(
                    id="./",
                    name=crate.name or crate_dir.name,
                    path=crate_dir,
                    entity_type="Dataset",
                    encoding_format=_get_prop_str(root, "encodingFormat"),
                    additional_type=root_additional,
                    description=crate.description or "",
                    crate_dir=crate_dir,
                )
            )

        # Individual data entities (files, datasets)
        for entity in crate.data_entities:
            eid = entity.id
            path = crate_dir / eid.rstrip("/")
            if not path.exists():
                continue

            fmt = _get_prop_str(entity, "encodingFormat")
            if not fmt:
                fmt = self._guess_format(path)

            entities.append(
                DataEntity(
                    id=eid,
                    name=_get_prop_str(entity, "name") or path.stem,
                    path=path,
                    entity_type=entity.type if isinstance(entity.type, str) else entity.type[0],
                    encoding_format=fmt,
                    additional_type=_get_prop_str(entity, "additionalType"),
                    description=_get_prop_str(entity, "description"),
                    crate_dir=crate_dir,
                    variables_measured=_extract_variables_measured(entity),
                )
            )

        # Fallback: discover by extension if no data entities found
        if not entities:
            entities = self._discover_by_extension(crate_dir)

        return entities

    def create_run_crate(
        self,
        output_dir: Union[str, Path],
        name: str,
        description: str,
        bindings: Optional[ResolvedBindings] = None,
        output_files: Optional[Dict[str, Path]] = None,
    ) -> Path:
        """
        Create a Workflow Run Crate for the pipeline output.

        Uses the rocrate library to build a proper RO-Crate with
        CreateAction provenance (Process Run Crate profile).

        Parameters
        ----------
        output_dir : str or Path
            Directory to write the crate into.
        name : str
            Name of the output crate.
        description : str
            Description of what this run produced.
        bindings : ResolvedBindings, optional
            The input bindings (to record provenance).
        output_files : dict, optional
            Mapping of description -> file path for output files.

        Returns
        -------
        Path
            Path to the created ro-crate-metadata.json.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        import json as _json

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        graph = [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": [
                    {"@id": "https://w3id.org/ro/crate/1.1"},
                    {"@id": "https://w3id.org/ro/wfrun/process/0.5"},
                ],
                "about": {"@id": "./"},
            },
        ]

        has_part = []

        # Add output files
        result_refs = []
        if output_files:
            for desc, fpath in output_files.items():
                fpath = Path(fpath)
                if fpath.exists():
                    fmt = self._guess_format(fpath)
                    entry = {
                        "@id": fpath.name,
                        "@type": "File",
                        "name": fpath.name,
                        "description": desc,
                    }
                    if fmt:
                        entry["encodingFormat"] = fmt
                    graph.append(entry)
                    result_refs.append({"@id": fpath.name})
                    has_part.append({"@id": fpath.name})

        # Record input provenance
        object_refs = []
        if bindings:
            for param_name, b in bindings.bindings.items():
                # Use a unique ID for inputs; avoid "./" which clashes with root
                entity_id = b.entity.id
                if entity_id == "./":
                    entity_id = f"#input-{param_name}"
                entry = {
                    "@id": entity_id,
                    "@type": "File" if b.entity.path.is_file() else "Dataset",
                    "name": b.entity.name,
                    "description": b.entity.description or "",
                }
                if b.entity.encoding_format:
                    entry["encodingFormat"] = b.entity.encoding_format
                if b.entity.additional_type:
                    entry["additionalType"] = b.entity.additional_type
                graph.append(entry)
                object_refs.append({"@id": entity_id})

        # CreateAction for provenance
        if result_refs or object_refs:
            action = {
                "@id": "#run",
                "@type": "CreateAction",
                "name": name,
            }
            if object_refs:
                action["object"] = object_refs
            if result_refs:
                action["result"] = result_refs
            graph.append(action)

        # Root dataset
        root = {
            "@id": "./",
            "@type": "Dataset",
            "name": name,
            "description": description,
        }
        if has_part:
            root["hasPart"] = has_part
        graph.insert(1, root)

        metadata = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": graph,
        }
        meta_path = output_dir / "ro-crate-metadata.json"
        with open(meta_path, "w") as f:
            _json.dump(metadata, f, indent=2)

        return output_dir / "ro-crate-metadata.json"

    # ── Private helpers ──

    def _discover_data_entities(self, input_dir: Path) -> List[DataEntity]:
        """Find all data entities across all RO-Crates in input_dir."""
        entities = []
        for meta_file in input_dir.rglob("ro-crate-metadata.json"):
            crate_entities = self.read_crate(meta_file.parent)
            entities.extend(crate_entities)
        return entities

    def _match(
        self, entities: List[DataEntity], min_score: float = 0.5
    ) -> ResolvedBindings:
        """Match data entities to formal parameters using scored matching."""
        bindings = {}
        used_entities = set()

        # Score all parameter-entity pairs
        scores = []
        for param in self.parameters:
            for entity in entities:
                score = param.matches(entity)
                if score >= min_score:
                    scores.append((score, param, entity))

        # Greedy assignment: best scores first
        scores.sort(key=lambda x: x[0], reverse=True)

        for score, param, entity in scores:
            if param.name in bindings:
                continue
            if id(entity) in used_entities:
                continue
            bindings[param.name] = Binding(
                parameter=param, entity=entity, score=score
            )
            used_entities.add(id(entity))

        unmatched_params = [p for p in self.parameters if p.name not in bindings]
        unmatched_entities = [e for e in entities if id(e) not in used_entities]

        return ResolvedBindings(
            bindings=bindings,
            unmatched_params=unmatched_params,
            unmatched_entities=unmatched_entities,
        )

    def _guess_format(self, path: Path) -> str:
        """Guess encoding format from file extension."""
        return self.formats.get(path.suffix.lower(), "")

    def _discover_by_extension(self, crate_dir: Path) -> List[DataEntity]:
        """Find data files in a crate directory by extension."""
        entities = []
        for ext, fmt in self.formats.items():
            for path in crate_dir.glob(f"*{ext}"):
                if path.name == "ro-crate-metadata.json":
                    continue
                entities.append(
                    DataEntity(
                        id=path.name,
                        name=path.stem,
                        path=path,
                        encoding_format=fmt,
                        crate_dir=crate_dir,
                    )
                )
        # GDB directories
        for gdb in crate_dir.glob("*.gdb"):
            if gdb.is_dir():
                entities.append(
                    DataEntity(
                        id=f"{gdb.name}/",
                        name=gdb.stem,
                        path=gdb,
                        entity_type="Dataset",
                        encoding_format="application/x-filegdb",
                        crate_dir=crate_dir,
                    )
                )
        return entities


# ── Module-level helpers ──


def _entity_to_formal_parameter(entity) -> FormalParameter:
    """Convert a rocrate entity to a FormalParameter."""
    # rocrate auto-dereferences @id refs, so entity properties
    # may return Entity objects for linked values
    return FormalParameter(
        id=entity.id,
        name=_get_prop_str(entity, "name") or entity.id,
        additional_type=_get_prop_str(entity, "additionalType"),
        encoding_formats=_get_prop_list(entity, "encodingFormat"),
        value_required=entity.get("valueRequired", True),
        default_value=entity.get("defaultValue"),
        description=_get_prop_str(entity, "description"),
        conforms_to=_get_prop_str(entity, "conformsTo"),
        variables_measured=_extract_variables_measured(entity),
    )


def _get_prop_str(entity, prop: str) -> str:
    """Get a string property from a rocrate entity.

    Handles cases where the value is a string, an Entity object
    (auto-dereferenced @id), or None.
    """
    value = entity.get(prop)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        # Return first element as string
        if not value:
            return ""
        item = value[0]
        return item.id if hasattr(item, "id") else str(item)
    # Entity object (auto-dereferenced)
    if hasattr(value, "id"):
        return value.id
    return str(value)


def _get_prop_list(entity, prop: str) -> List[str]:
    """Get a list of string values from a rocrate entity property.

    Handles string, list of strings, Entity, or list of Entities.
    """
    value = entity.get(prop)
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif hasattr(item, "id"):
                result.append(item.id)
            else:
                result.append(str(item))
        return result
    # Single Entity object
    if hasattr(value, "id"):
        return [value.id]
    return [str(value)]


def _extract_variables_measured(entity) -> List[VariableDescription]:
    """Extract variableMeasured from a rocrate entity as VariableDescriptions.

    Handles both inline PropertyValue objects and @id references to
    separate entities in the crate. Each variable should have at least
    a name; propertyID is the semantic identifier (e.g. I-ADOPT nanopub URI).
    """
    value = entity.get("variableMeasured")
    if value is None:
        return []

    if not isinstance(value, list):
        value = [value]

    variables = []
    for item in value:
        if isinstance(item, str):
            variables.append(VariableDescription(name=item))
        elif isinstance(item, dict):
            variables.append(
                VariableDescription(
                    name=item.get("name", ""),
                    property_id=item.get("propertyID", ""),
                    description=item.get("description", ""),
                    role=item.get("additionalType", ""),
                )
            )
        elif hasattr(item, "get"):
            # rocrate Entity object (auto-dereferenced)
            variables.append(
                VariableDescription(
                    name=_get_prop_str(item, "name"),
                    property_id=_get_prop_str(item, "propertyID"),
                    description=_get_prop_str(item, "description"),
                    role=_get_prop_str(item, "additionalType"),
                )
            )

    return variables


def _formats_compatible(expected: str, actual: str) -> bool:
    """Check if two format identifiers are compatible (loose matching)."""
    if expected == actual:
        return True
    # Normalize common variations
    norm = {
        "application/geo+json": {"application/geojson", "application/vnd.geo+json"},
        "image/tiff": {"image/geotiff", "image/x-geotiff"},
    }
    expected_set = norm.get(expected, {expected})
    actual_set = norm.get(actual, {actual})
    return bool(expected_set & actual_set)

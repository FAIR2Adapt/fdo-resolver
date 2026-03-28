"""Tests for fdo_resolver."""

import json
from pathlib import Path

import pytest

from fdo_resolver import FDOResolver, ResolvedBindings
from fdo_resolver.resolver import (
    DataEntity,
    FormalParameter,
    _get_prop_str,
    _formats_compatible,
)


@pytest.fixture
def tmp_workflow_crate(tmp_path):
    """Create a minimal Workflow RO-Crate with two input parameters."""
    crate_dir = tmp_path / "workflow-crate"
    crate_dir.mkdir()

    metadata = {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": [
                    {"@id": "https://w3id.org/ro/crate/1.1"},
                    {"@id": "https://w3id.org/workflowhub/workflow-ro-crate/1.0"},
                ],
                "about": {"@id": "./"},
            },
            {
                "@id": "./",
                "@type": "Dataset",
                "name": "Test Workflow",
                "mainEntity": {"@id": "workflow.py"},
                "hasPart": [{"@id": "workflow.py"}],
            },
            {
                "@id": "workflow.py",
                "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
                "name": "Test Workflow",
                "input": [
                    {"@id": "#param-flood"},
                    {"@id": "#param-buildings"},
                ],
                "output": [],
            },
            {
                "@id": "#param-flood",
                "@type": "FormalParameter",
                "name": "flood_data",
                "encodingFormat": "application/geo+json",
                "additionalType": "https://example.org/FloodData",
                "valueRequired": True,
                "description": "Flood level GeoJSON layers",
            },
            {
                "@id": "#param-buildings",
                "@type": "FormalParameter",
                "name": "buildings",
                "encodingFormat": "application/x-filegdb",
                "valueRequired": True,
                "description": "Building footprints as GDB",
            },
        ],
    }

    # Write a placeholder workflow file so the crate is valid
    (crate_dir / "workflow.py").write_text("# workflow")
    with open(crate_dir / "ro-crate-metadata.json", "w") as f:
        json.dump(metadata, f)

    return crate_dir


@pytest.fixture
def tmp_data_crates(tmp_path):
    """Create two data RO-Crates: one with a GeoJSON, one with a GDB."""
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()

    # Flood data crate
    flood_dir = input_dir / "flood-crate"
    flood_dir.mkdir()
    (flood_dir / "flood_30.geojson").write_text('{"type": "FeatureCollection"}')
    flood_meta = {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                "about": {"@id": "./"},
            },
            {
                "@id": "./",
                "@type": "Dataset",
                "name": "Flood Levels",
                "description": "Pluvial flood level data",
                "hasPart": [{"@id": "flood_30.geojson"}],
            },
            {
                "@id": "flood_30.geojson",
                "@type": "File",
                "name": "flood_data",
                "encodingFormat": "application/geo+json",
                "additionalType": "https://example.org/FloodData",
            },
        ],
    }
    with open(flood_dir / "ro-crate-metadata.json", "w") as f:
        json.dump(flood_meta, f)

    # Buildings data crate (GDB directory)
    bldg_dir = input_dir / "buildings-crate"
    bldg_dir.mkdir()
    gdb = bldg_dir / "buildings.gdb"
    gdb.mkdir()
    (gdb / "dummy").write_text("")  # GDB needs at least one file
    bldg_meta = {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                "about": {"@id": "./"},
            },
            {
                "@id": "./",
                "@type": "Dataset",
                "name": "Building Footprints",
                "hasPart": [{"@id": "buildings.gdb/"}],
            },
            {
                "@id": "buildings.gdb/",
                "@type": "Dataset",
                "name": "buildings",
                "encodingFormat": "application/x-filegdb",
            },
        ],
    }
    with open(bldg_dir / "ro-crate-metadata.json", "w") as f:
        json.dump(bldg_meta, f)

    return input_dir


# ── Unit tests ──


class TestFormalParameter:
    def test_exact_format_match(self):
        param = FormalParameter(
            id="#p", name="data", encoding_formats=["application/geo+json"]
        )
        entity = DataEntity(
            id="f.geojson",
            name="data",
            path=Path("/f.geojson"),
            encoding_format="application/geo+json",
        )
        assert param.matches(entity) > 0.5

    def test_name_match(self):
        param = FormalParameter(id="#p", name="flood_data")
        entity = DataEntity(
            id="flood_data.geojson", name="flood_data", path=Path("/f.geojson")
        )
        assert param.matches(entity) > 0.5

    def test_no_match(self):
        param = FormalParameter(
            id="#p",
            name="buildings",
            encoding_formats=["application/x-filegdb"],
        )
        entity = DataEntity(
            id="flood.geojson",
            name="flood",
            path=Path("/f.geojson"),
            encoding_format="application/geo+json",
        )
        assert param.matches(entity) < 0.5


class TestGetPropStr:
    def test_string_property(self, tmp_path):
        """Test extracting a plain string property from a rocrate entity."""
        from rocrate.rocrate import ROCrate
        crate = ROCrate()
        f = crate.add_file(str(tmp_path / "dummy"), properties={
            "name": "test_file",
            "encodingFormat": "text/csv",
        })
        # Ensure the file exists for the crate
        (tmp_path / "dummy").write_text("")
        assert _get_prop_str(f, "name") == "test_file"
        assert _get_prop_str(f, "encodingFormat") == "text/csv"

    def test_missing_property(self, tmp_path):
        """Test that missing properties return empty string."""
        from rocrate.rocrate import ROCrate
        crate = ROCrate()
        (tmp_path / "dummy").write_text("")
        f = crate.add_file(str(tmp_path / "dummy"))
        assert _get_prop_str(f, "additionalType") == ""


class TestFormatsCompatible:
    def test_exact(self):
        assert _formats_compatible("image/tiff", "image/tiff")

    def test_geojson_variant(self):
        assert _formats_compatible("application/geo+json", "application/geojson")

    def test_incompatible(self):
        assert not _formats_compatible("application/geo+json", "text/csv")


# ── Integration tests ──


class TestFromWorkflowCrate:
    def test_loads_parameters(self, tmp_workflow_crate):
        resolver = FDOResolver.from_workflow_crate(tmp_workflow_crate)
        assert len(resolver.parameters) == 2
        names = {p.name for p in resolver.parameters}
        assert names == {"flood_data", "buildings"}

    def test_parameter_details(self, tmp_workflow_crate):
        resolver = FDOResolver.from_workflow_crate(tmp_workflow_crate)
        flood = next(p for p in resolver.parameters if p.name == "flood_data")
        assert flood.encoding_format == "application/geo+json"
        assert flood.additional_type == "https://example.org/FloodData"
        assert flood.value_required is True

    def test_missing_metadata_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            FDOResolver.from_workflow_crate(tmp_path)

    def test_no_workflow_raises(self, tmp_path):
        """A valid RO-Crate with no ComputationalWorkflow should raise ValueError."""
        meta = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": [
                {
                    "@id": "ro-crate-metadata.json",
                    "@type": "CreativeWork",
                    "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                    "about": {"@id": "./"},
                },
                {"@id": "./", "@type": "Dataset", "name": "Empty"},
            ],
        }
        with open(tmp_path / "ro-crate-metadata.json", "w") as f:
            json.dump(meta, f)
        with pytest.raises(ValueError, match="No ComputationalWorkflow"):
            FDOResolver.from_workflow_crate(tmp_path)


class TestFromParameters:
    def test_creates_resolver(self):
        resolver = FDOResolver.from_parameters(
            [
                {"name": "input_a", "encoding_format": "text/csv"},
                {"name": "input_b", "value_required": False},
            ]
        )
        assert len(resolver.parameters) == 2
        assert resolver.parameters[1].value_required is False


class TestResolve:
    def test_full_resolution(self, tmp_workflow_crate, tmp_data_crates):
        resolver = FDOResolver.from_workflow_crate(tmp_workflow_crate)
        result = resolver.resolve(tmp_data_crates)

        assert isinstance(result, ResolvedBindings)
        assert result.is_complete
        assert "flood_data" in result.bindings
        assert "buildings" in result.bindings
        assert result.bindings["flood_data"].entity.encoding_format == "application/geo+json"
        assert result.bindings["buildings"].entity.encoding_format == "application/x-filegdb"

    def test_partial_resolution(self, tmp_workflow_crate, tmp_data_crates):
        # Remove one data crate
        import shutil

        shutil.rmtree(tmp_data_crates / "buildings-crate")

        resolver = FDOResolver.from_workflow_crate(tmp_workflow_crate)
        result = resolver.resolve(tmp_data_crates)

        assert not result.is_complete
        assert "flood_data" in result.bindings
        assert len(result.unmatched_params) == 1
        assert result.unmatched_params[0].name == "buildings"

    def test_paths_property(self, tmp_workflow_crate, tmp_data_crates):
        resolver = FDOResolver.from_workflow_crate(tmp_workflow_crate)
        result = resolver.resolve(tmp_data_crates)
        paths = result.paths

        assert "flood_data" in paths
        assert "buildings" in paths
        assert paths["flood_data"].suffix == ".geojson"


class TestReadCrate:
    def test_reads_data_entities(self, tmp_data_crates):
        resolver = FDOResolver()
        entities = resolver.read_crate(tmp_data_crates / "flood-crate")
        assert len(entities) == 1
        assert entities[0].encoding_format == "application/geo+json"

    def test_reads_gdb(self, tmp_data_crates):
        resolver = FDOResolver()
        entities = resolver.read_crate(tmp_data_crates / "buildings-crate")
        assert len(entities) >= 1
        gdb_entities = [e for e in entities if e.encoding_format == "application/x-filegdb"]
        assert len(gdb_entities) >= 1
        assert gdb_entities[0].path.name == "buildings.gdb"

    def test_empty_dir(self, tmp_path):
        resolver = FDOResolver()
        assert resolver.read_crate(tmp_path) == []

    def test_fallback_discovery(self, tmp_path):
        """Crate with metadata but no File entities -> discover by extension."""
        crate_dir = tmp_path / "bare-crate"
        crate_dir.mkdir()
        (crate_dir / "data.csv").write_text("a,b\n1,2")
        meta = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": [
                {
                    "@id": "ro-crate-metadata.json",
                    "@type": "CreativeWork",
                    "about": {"@id": "./"},
                },
                {"@id": "./", "@type": "Dataset", "name": "Bare"},
            ],
        }
        with open(crate_dir / "ro-crate-metadata.json", "w") as f:
            json.dump(meta, f)

        resolver = FDOResolver()
        entities = resolver.read_crate(crate_dir)
        assert len(entities) == 1
        assert entities[0].encoding_format == "text/csv"


class TestCreateRunCrate:
    def test_creates_metadata(self, tmp_path):
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "result.geojson").write_text('{"type": "FeatureCollection"}')

        resolver = FDOResolver()
        meta_path = resolver.create_run_crate(
            output_dir,
            name="Test Run",
            description="A test run",
            output_files={"Risk layer": output_dir / "result.geojson"},
        )

        assert meta_path.exists()
        with open(meta_path) as f:
            metadata = json.load(f)

        graph = metadata["@graph"]
        root = next(e for e in graph if e["@id"] == "./")
        assert root["name"] == "Test Run"

        file_entity = next(e for e in graph if e.get("@id") == "result.geojson")
        assert file_entity["encodingFormat"] == "application/geo+json"


class TestSummary:
    def test_summary_output(self, tmp_workflow_crate, tmp_data_crates):
        resolver = FDOResolver.from_workflow_crate(tmp_workflow_crate)
        result = resolver.resolve(tmp_data_crates)
        summary = result.summary()
        assert "flood_data" in summary
        assert "buildings" in summary


class TestVariableMeasured:
    """Test I-ADOPT variable matching via variableMeasured / propertyID."""

    # Placeholder I-ADOPT nanopub URIs (will be real URIs once namespace is deployed)
    ELDERLY_SINGLES_URI = "https://w3id.org/np/RA-elderly-singles-placeholder"
    CHILDREN_URI = "https://w3id.org/np/RA-children-placeholder"
    WELFARE_URI = "https://w3id.org/np/RA-welfare-recipients-placeholder"

    def test_column_mapping_via_property_id(self):
        """Matching by I-ADOPT propertyID produces correct column mapping."""
        from fdo_resolver.resolver import VariableDescription

        param = FormalParameter(
            id="#p",
            name="buildings",
            encoding_formats=["application/flatgeobuf"],
            variables_measured=[
                VariableDescription(
                    name="elderly_singles",
                    property_id=self.ELDERLY_SINGLES_URI,
                    role="sensitivity_indicator",
                ),
                VariableDescription(
                    name="children",
                    property_id=self.CHILDREN_URI,
                    role="sensitivity_indicator",
                ),
            ],
        )

        entity = DataEntity(
            id="buildings.fgb",
            name="buildings",
            path=Path("/data/buildings.fgb"),
            encoding_format="application/flatgeobuf",
            variables_measured=[
                VariableDescription(
                    name="ES",  # Hamburg column name
                    property_id=self.ELDERLY_SINGLES_URI,
                ),
                VariableDescription(
                    name="C",  # Hamburg column name
                    property_id=self.CHILDREN_URI,
                ),
                VariableDescription(
                    name="WR",  # present but not requested
                    property_id=self.WELFARE_URI,
                ),
            ],
        )

        # Check matching score includes variable match
        score = param.matches(entity)
        assert score > 0.5

        # Check column mapping
        from fdo_resolver.resolver import Binding

        binding = Binding(parameter=param, entity=entity, score=score)
        mapping = binding.column_mapping
        assert mapping == {"elderly_singles": "ES", "children": "C"}

    def test_no_variables_no_mapping(self):
        """When no variableMeasured, column_mapping is empty."""
        from fdo_resolver.resolver import Binding

        param = FormalParameter(id="#p", name="data")
        entity = DataEntity(id="f.csv", name="data", path=Path("/f.csv"))
        binding = Binding(parameter=param, entity=entity, score=1.0)
        assert binding.column_mapping == {}

    def test_partial_variable_match(self):
        """Only matching propertyIDs appear in column_mapping."""
        from fdo_resolver.resolver import VariableDescription, Binding

        param = FormalParameter(
            id="#p",
            name="data",
            variables_measured=[
                VariableDescription(name="var_a", property_id="https://example.org/A"),
                VariableDescription(name="var_b", property_id="https://example.org/B"),
            ],
        )
        entity = DataEntity(
            id="data.csv",
            name="data",
            path=Path("/data.csv"),
            variables_measured=[
                VariableDescription(name="col_a", property_id="https://example.org/A"),
                # var_b not present in data
            ],
        )
        binding = Binding(parameter=param, entity=entity, score=1.0)
        assert binding.column_mapping == {"var_a": "col_a"}
        assert "var_b" not in binding.column_mapping

    def test_from_parameters_with_variables(self):
        """from_parameters() accepts variables_measured dicts."""
        resolver = FDOResolver.from_parameters([
            {
                "name": "buildings",
                "encoding_format": "application/flatgeobuf",
                "variables_measured": [
                    {
                        "name": "elderly_singles",
                        "property_id": self.ELDERLY_SINGLES_URI,
                        "role": "sensitivity_indicator",
                    },
                ],
            },
        ])
        assert len(resolver.parameters) == 1
        assert len(resolver.parameters[0].variables_measured) == 1
        assert resolver.parameters[0].variables_measured[0].property_id == self.ELDERLY_SINGLES_URI

    def test_variable_match_in_rocrate(self, tmp_path):
        """variableMeasured in RO-Crate metadata is extracted and matched."""
        # Create a data crate with variableMeasured as separate entities
        # (rocrate library requires @id on nested objects)
        crate_dir = tmp_path / "data-crate"
        crate_dir.mkdir()
        (crate_dir / "buildings.fgb").write_bytes(b"fake")

        meta = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": [
                {
                    "@id": "ro-crate-metadata.json",
                    "@type": "CreativeWork",
                    "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                    "about": {"@id": "./"},
                },
                {
                    "@id": "./",
                    "@type": "Dataset",
                    "name": "Buildings",
                    "hasPart": [{"@id": "buildings.fgb"}],
                },
                {
                    "@id": "buildings.fgb",
                    "@type": "File",
                    "name": "buildings",
                    "encodingFormat": "application/flatgeobuf",
                    "variableMeasured": [
                        {"@id": "#var-es"},
                        {"@id": "#var-c"},
                    ],
                },
                {
                    "@id": "#var-es",
                    "@type": "PropertyValue",
                    "name": "ES",
                    "propertyID": self.ELDERLY_SINGLES_URI,
                    "description": "Number of elderly singles",
                },
                {
                    "@id": "#var-c",
                    "@type": "PropertyValue",
                    "name": "C",
                    "propertyID": self.CHILDREN_URI,
                },
            ],
        }
        with open(crate_dir / "ro-crate-metadata.json", "w") as f:
            json.dump(meta, f)

        resolver = FDOResolver()
        entities = resolver.read_crate(crate_dir)
        assert len(entities) == 1

        entity = entities[0]
        assert len(entity.variables_measured) == 2
        assert entity.variables_measured[0].name == "ES"
        assert entity.variables_measured[0].property_id == self.ELDERLY_SINGLES_URI
        assert entity.variables_measured[1].name == "C"

import pytest

from phenix_apps.testing.readme import readme_components, readme_section, readme_yaml

README = """# thing Component

## Examples

```yaml
components:
  - name: one
    type: thing
  - name: other
    type: else
```

Some text.

```yaml
components:
  - name: two
    type: thing
```

## Limitations

```yaml
components:
  - name: not-an-example
    type: thing
```
"""


@pytest.fixture
def readme(tmp_path):
    path = tmp_path / "README.md"
    path.write_text(README)
    return path


def test_components_come_from_the_named_section_only(readme):
    names = [c["name"] for c in readme_components(readme, "thing")]
    assert names == ["one", "two"]


def test_yaml_blocks_and_sections(readme):
    assert len(readme_yaml(readme, "Limitations")) == 1
    assert readme_section(readme, "Examples").strip().startswith("```yaml")


def test_missing_section_fails_clearly(readme):
    with pytest.raises(AssertionError, match="no '## Troubleshooting' section"):
        readme_section(readme, "Troubleshooting")

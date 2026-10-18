"""Contract tests for Path B marketing, discoverability, and metadata integrity.

Ensures adherence to:
- T-20260920-167562623 (version invariance on Pfad B runs)
- Multilingual README parity and badge currency
- Mermaid diagram syntax safety
- AI/RAG context freshness in llms.txt
- Marketing log existence and recommendations
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_version_frozen_per_t_20260920():
    """Verify that version 3.15.0 is strictly preserved and not modified."""
    setup_py = REPO_ROOT / "setup.py"
    pyproject = REPO_ROOT / "pyproject.toml"

    assert setup_py.is_file(), "setup.py must exist"
    assert pyproject.is_file(), "pyproject.toml must exist"

    setup_content = setup_py.read_text(encoding="utf-8")
    assert 'version="3.15.0"' in setup_content or "version='3.15.0'" in setup_content, (
        "setup.py must maintain version 3.15.0"
    )

    pyproject_content = pyproject.read_text(encoding="utf-8")
    assert 'version = "3.15.0"' in pyproject_content, (
        "pyproject.toml must maintain version 3.15.0"
    )


def test_readmes_badges_currency():
    """Verify badges currency and legal disclaimers in English and German READMEs."""
    readme_en = REPO_ROOT / "README.md"
    readme_de = REPO_ROOT / "README.de.md"

    assert readme_en.is_file(), "README.md must exist"
    assert readme_de.is_file(), "README.de.md must exist"

    content_en = readme_en.read_text(encoding="utf-8")
    content_de = readme_de.read_text(encoding="utf-8")

    # Audit date
    assert "2026--10--18" in content_en or "2026-10-18" in content_en, (
        "README.md must contain 2026-10-18 audit badge"
    )
    assert "2026--10--18" in content_de or "2026-10-18" in content_de, (
        "README.de.md must contain 2026-10-18 audit badge"
    )

    # § 521 BGB liability badge and section
    assert "521" in content_en, "README.md must cite § 521 BGB"
    assert "521" in content_de, "README.de.md must cite § 521 BGB"

    # Security SLA badge
    assert "48h" in content_en, "README.md must include 48h Security SLA"
    assert "48h" in content_de, "README.de.md must include 48h Security SLA"


def test_readmes_mermaid_diagrams_valid():
    """Verify that both README.md and README.de.md have valid, lint-safe Mermaid diagrams."""
    mermaid_block_re = re.compile(r"```mermaid\s*\n(.*?)\n```", re.DOTALL)
    for readme_path in [REPO_ROOT / "README.md", REPO_ROOT / "README.de.md"]:
        content = readme_path.read_text(encoding="utf-8")
        blocks = mermaid_block_re.findall(content)
        assert len(blocks) >= 2, f"{readme_path.name} must have at least 2 Mermaid diagrams"

        for idx, block in enumerate(blocks, start=1):
            # Check balanced subgraphs
            subgraph_count = len(re.findall(r"\bsubgraph\b", block))
            end_count = len(re.findall(r"\bend\b", block))
            assert subgraph_count == end_count, (
                f"Block {idx} in {readme_path.name} has unbalanced subgraphs ({subgraph_count} vs {end_count})"
            )

            # Check sequence diagram message rules
            if "sequenceDiagram" in block:
                for line in block.splitlines():
                    if "->>" in line or "-->>" in line:
                        assert ";" not in line, (
                            f"Semicolons not allowed in sequence diagram messages: {line}"
                        )


def test_llms_txt_freshness():
    """Verify llms.txt RAG index reflects v3.15.0 and audit date."""
    llms_txt = REPO_ROOT / "llms.txt"
    assert llms_txt.is_file(), "llms.txt must exist"

    content = llms_txt.read_text(encoding="utf-8")
    assert "v3.15.0" in content, "llms.txt must state current version v3.15.0"
    assert "Last-checked: 2026-10-18" in content, "llms.txt must reflect current audit date"
    assert "MARKETING-LOG.txt" in content, "llms.txt must link to MARKETING-LOG.txt"


def test_marketing_log_recency_and_recommendations():
    """Verify MARKETING-LOG.txt exists, contains audit details and recommendations."""
    marketing_log = REPO_ROOT / "MARKETING-LOG.txt"
    assert marketing_log.is_file(), "MARKETING-LOG.txt must exist in repo root"

    content = marketing_log.read_text(encoding="utf-8")
    assert "2026-10-18" in content, "MARKETING-LOG.txt must reflect audit date 2026-10-18"
    assert "Pfad B" in content or "PATH_B" in content, "MARKETING-LOG.txt must note Path B"
    assert "REC-20261018-01" in content, "Must include recommendation REC-20261018-01"
    assert "REC-20261018-02" in content, "Must include recommendation REC-20261018-02"
    assert "REC-20261018-03" in content, "Must include recommendation REC-20261018-03"

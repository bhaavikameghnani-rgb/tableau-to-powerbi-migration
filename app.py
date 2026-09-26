import json
import shutil
import subprocess
import sys
from pathlib import Path

import streamlit as st


# =========================================================
# Configuration
# =========================================================

PROJECT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_DIR / "scripts"
RUN_DIR = PROJECT_DIR / "_runs"

RUN_DIR.mkdir(exist_ok=True)


# =========================================================
# Page configuration
# =========================================================

st.set_page_config(
    page_title="Tableau → Power BI Validator",
    page_icon="📊",
    layout="wide",
)


# =========================================================
# Styling
# =========================================================

st.markdown(
    """
    <style>
    .main-title {
        font-size: 32px;
        font-weight: 700;
        margin-bottom: 5px;
    }

    .subtitle {
        color: #666;
        font-size: 16px;
        margin-bottom: 25px;
    }

    .status-pass {
        color: #16803c;
        font-size: 26px;
        font-weight: 700;
    }

    .status-fail {
        color: #c62828;
        font-size: 26px;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# Header
# =========================================================

st.markdown(
    '<div class="main-title">Tableau → Power BI Migration Validator</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="subtitle">'
    "Compare a Tableau workbook with its migrated Power BI report"
    "</div>",
    unsafe_allow_html=True,
)


# =========================================================
# File Upload
# =========================================================

st.subheader("Migration Files")

col1, col2 = st.columns(2)

with col1:
    st.markdown("### 1. Tableau Workbook")

    tableau_file = st.file_uploader(
        "Upload Tableau workbook",
        type=["twbx", "twb"],
        key="tableau_file",
    )

with col2:
    st.markdown("### 2. Power BI Report")

    powerbi_file = st.file_uploader(
        "Upload Power BI report",
        type=["pbix"],
        key="powerbi_file",
    )


# =========================================================
# Selected Files
# =========================================================

if tableau_file or powerbi_file:

    st.divider()
    st.subheader("Selected Files")

    col1, col2 = st.columns(2)

    with col1:

        if tableau_file:

            st.success(
                f"✓ {tableau_file.name}\n\n"
                f"Size: {tableau_file.size / (1024 * 1024):.2f} MB"
            )

    with col2:

        if powerbi_file:

            st.success(
                f"✓ {powerbi_file.name}\n\n"
                f"Size: {powerbi_file.size / (1024 * 1024):.2f} MB"
            )


# =========================================================
# Run Validation
# =========================================================

if st.button(
    "▶ Run Validation",
    type="primary",
    use_container_width=True,
):

    if not tableau_file:

        st.error("Please upload a Tableau workbook.")
        st.stop()

    if not powerbi_file:

        st.error("Please upload a Power BI report.")
        st.stop()


    # -----------------------------------------------------
    # Create run directory
    # -----------------------------------------------------

    run_name = (
        Path(tableau_file.name)
        .stem
        .replace(" ", "_")
        .replace("-", "_")
    )

    run_dir = RUN_DIR / run_name

    if run_dir.exists():

        shutil.rmtree(run_dir)

    run_dir.mkdir(parents=True)


    # -----------------------------------------------------
    # Save uploaded files
    # -----------------------------------------------------

    tableau_path = run_dir / tableau_file.name
    pbix_path = run_dir / powerbi_file.name

    with open(tableau_path, "wb") as f:

        f.write(tableau_file.getbuffer())

    with open(pbix_path, "wb") as f:

        f.write(powerbi_file.getbuffer())


    # -----------------------------------------------------
    # Output locations
    # -----------------------------------------------------

    migration_spec = run_dir / "migration-spec.json"

    report_dir = (
        run_dir /
        f"{Path(powerbi_file.name).stem}.Report"
    )

    powerbi_visuals = run_dir / "powerbi-visuals.json"

    validation_file = run_dir / "validation.json"


    # =====================================================
    # Step 1 — Parse Tableau
    # =====================================================

    st.subheader("Migration Process")

    progress = st.progress(0)

    with st.status(
        "Parsing Tableau workbook...",
        expanded=True,
    ) as status:

        command = [
            sys.executable,
            str(SCRIPTS_DIR / "parse_tableau.py"),
            str(tableau_path),
            "-o",
            str(migration_spec),
        ]

        result = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
        )

        if result.stdout:

            st.code(
                result.stdout,
                language="text",
            )

        if result.returncode != 0:

            status.update(
                label="Tableau parsing failed",
                state="error",
            )

            if result.stderr:

                st.code(
                    result.stderr,
                    language="text",
                )

            st.stop()

        status.update(
            label="✓ Tableau workbook parsed",
            state="complete",
        )

    progress.progress(25)


    # =====================================================
    # Step 2 — Extract Power BI
    # =====================================================

    with st.status(
        "Extracting Power BI report...",
        expanded=True,
    ) as status:

        command = [
            sys.executable,
            str(SCRIPTS_DIR / "extract_pbix_report.py"),
            str(pbix_path),
            "-o",
            str(report_dir),
        ]

        result = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
        )

        if result.stdout:

            st.code(
                result.stdout,
                language="text",
            )

        if result.returncode != 0:

            status.update(
                label="Power BI extraction failed",
                state="error",
            )

            if result.stderr:

                st.code(
                    result.stderr,
                    language="text",
                )

            st.stop()

        status.update(
            label="✓ Power BI report extracted",
            state="complete",
        )

    progress.progress(50)


    # =====================================================
    # Step 3 — Extract Power BI Visuals
    # =====================================================

    with st.status(
        "Analyzing Power BI visuals...",
        expanded=True,
    ) as status:

        command = [
            sys.executable,
            str(SCRIPTS_DIR / "extract_powerbi_visuals.py"),
            str(report_dir),
            "-o",
            str(powerbi_visuals),
        ]

        result = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
        )

        if result.stdout:

            st.code(
                result.stdout,
                language="text",
            )

        if result.returncode != 0:

            status.update(
                label="Power BI visual extraction failed",
                state="error",
            )

            if result.stderr:

                st.code(
                    result.stderr,
                    language="text",
                )

            st.stop()

        status.update(
            label="✓ Power BI visuals analyzed",
            state="complete",
        )

    progress.progress(70)


    # =====================================================
    # Step 4 — Validate Tableau vs Power BI
    # =====================================================

    with st.status(
        "Running Tableau → Power BI validation...",
        expanded=True,
    ) as status:

        command = [
            sys.executable,
            str(SCRIPTS_DIR / "validate_tableau_powerbi.py"),
            str(tableau_path),
            str(report_dir),
            "--migration-spec",
            str(migration_spec),
            "-o",
            str(validation_file),
        ]

        result = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
        )

        if result.stdout:

            st.code(
                result.stdout,
                language="text",
            )

        # The validator can return a non-zero exit code
        # when mismatches are detected. That is still a
        # valid validation result if validation.json exists.

        if result.returncode != 0 and not validation_file.exists():

            status.update(
                label="Validation failed to produce results",
                state="error",
            )

            if result.stderr:

                st.code(
                    result.stderr,
                    language="text",
                )

            st.stop()

        status.update(
            label="✓ Validation completed",
            state="complete",
        )

    progress.progress(100)


    # =====================================================
    # Load Validation Results
    # =====================================================

    if not validation_file.exists():

        st.error(
            "Validation completed but validation.json "
            "was not produced."
        )

        st.stop()


    with open(
        validation_file,
        "r",
        encoding="utf-8",
    ) as f:

        validation = json.load(f)


    st.session_state["validation"] = validation


# =========================================================
# Display Results
# =========================================================

if "validation" in st.session_state:

    validation = st.session_state["validation"]

    st.divider()

    st.subheader("Validation Summary")


    # -----------------------------------------------------
    # Summary values
    # -----------------------------------------------------

    status = str(
        validation.get(
            "status",
            "UNKNOWN",
        )
    ).upper()


    tableau_visuals = validation.get(
        "tableau_visuals",
        0,
    )

    powerbi_visuals = validation.get(
        "powerbi_visuals",
        0,
    )

    matched = validation.get(
        "matched",
        0,
    )

    passed = validation.get(
        "pass",
        validation.get(
            "passed",
            0,
        ),
    )

    warned = validation.get(
        "warn",
        validation.get(
            "warnings",
            0,
        ),
    )

    failed = validation.get(
        "fail",
        validation.get(
            "failed",
            0,
        ),
    )


    # -----------------------------------------------------
    # Metrics
    # -----------------------------------------------------

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric(
        "Tableau Visuals",
        tableau_visuals,
    )

    c2.metric(
        "Power BI Visuals",
        powerbi_visuals,
    )

    c3.metric(
        "Matched",
        matched,
    )

    c4.metric(
        "Passed",
        passed,
    )

    c5.metric(
        "Failed",
        failed,
    )


    # -----------------------------------------------------
    # Overall status
    # -----------------------------------------------------

    st.markdown("### Overall Status")


    if status == "PASS":

        st.markdown(
            '<div class="status-pass">'
            "✓ VALIDATION PASSED"
            "</div>",
            unsafe_allow_html=True,
        )

    else:

        st.markdown(
            '<div class="status-fail">'
            "✗ VALIDATION FAILED"
            "</div>",
            unsafe_allow_html=True,
        )


    # =====================================================
    # Validation Details
    # =====================================================

    st.divider()

    st.subheader("Validation Details")


    details = (
        validation.get("details")
        or validation.get("results")
        or validation.get("visuals")
        or []
    )


    if details:

        for item in details:

            if isinstance(item, dict):

                name = (
                    item.get("tableau_visual")
                    or item.get("name")
                    or item.get("visual")
                    or "Unnamed Visual"
                )


                item_status = str(
                    item.get("status")
                    or item.get("result")
                    or "UNKNOWN"
                ).upper()


                if item_status == "PASS":

                    st.success(
                        f"✓ {name}"
                    )

                elif item_status == "WARN":

                    st.warning(
                        f"⚠ {name}"
                    )

                else:

                    st.error(
                        f"✗ {name}"
                    )


                with st.expander(
                    "View details"
                ):

                    st.json(item)

            else:

                st.write(item)

    else:

        st.info(
            "The validator did not return "
            "individual visual-level details."
        )


    # =====================================================
    # Unexpected Power BI Visuals
    # =====================================================

    unexpected = validation.get(
        "unexpected_powerbi_visuals",
        [],
    )


    if unexpected:

        st.divider()

        st.subheader(
            "Additional Power BI Visuals"
        )


        st.info(
            f"{len(unexpected)} Power BI visuals "
            "were not directly matched to Tableau visuals."
        )


        with st.expander(
            "View additional visuals"
        ):

            st.json(unexpected)


    # =====================================================
    # Download Validation JSON
    # =====================================================

    st.divider()

    st.download_button(
        "Download Validation JSON",
        data=json.dumps(
            validation,
            indent=2,
        ),
        file_name="validation.json",
        mime="application/json",
    )


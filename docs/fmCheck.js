let generatedReportData = null;
const fmCheck_btnGenCompliance = document.getElementById("fmCheck_btnGenCompliance");

async function fmCheck_generateComplianceReport() {
    fmCheck_btnGenCompliance.disabled = true;

    if (!pyodide) {
        fmCheck_btnGenCompliance.textContent = "Loading Pyodide...";
        pyodide = await initPyodide();
    }

    fmCheck_btnGenCompliance.textContent = "Loading DICOMs...";
    const dicomFiles = await loadDICOMs("fmCheck_selectDICOMs");

    const referenceFile = document.getElementById("fmCheck_selectJsonReference").files[0];
    const referenceFileContent = await referenceFile.text();

    const isJson = referenceFile.name.endsWith(".json");
    const refFilePath = isJson ? "temp_json_ref.json" : "temp_py_ref.py";

    pyodide.FS.writeFile(refFilePath, referenceFileContent);

    fmCheck_btnGenCompliance.textContent = "Generating initial mapping...";

    pyodide.globals.set("dicom_files", dicomFiles);
    pyodide.globals.set("is_json", isJson);
    pyodide.globals.set("ref_path", refFilePath);

    const mappingOutput = await pyodide.runPythonAsync(`
        import json
        from dicompare.io import load_json_session, load_python_session, load_dicom_session
        from dicompare.mapping import map_to_json_reference

        if is_json:
            acquisition_fields, reference_fields, ref_session = load_json_session(ref_path)
        else:
            ref_models = load_python_session(module_path=ref_path)
            ref_session = {"acquisitions": {k: {} for k in ref_models.keys()}}
            acquisition_fields = ["ProtocolName"]

        in_session = load_dicom_session(
            dicom_bytes=dicom_files,
            acquisition_fields=acquisition_fields
        )

        if "PixelSpacing" not in in_session.columns:
            print("PixelSpacing is missing from the input session data.")
        else:
            print("PixelSpacing is present in the input session data.")

        input_acquisitions = list(in_session['Acquisition'].unique())

        if is_json:
            in_session["Series"] = (
                in_session.groupby(reference_fields, dropna=False).ngroup().add(1).apply(lambda x: f"Series {x}")
            )
            session_map = map_to_json_reference(in_session, ref_session)
            session_map_serializable = {
                f"{key[0]}::{key[1]}": f"{value[0]}::{value[1]}"
                for key, value in session_map.items()
            }
        else:
            session_map_serializable = {}

        json.dumps({
            "reference_acquisitions": ref_session["acquisitions"],
            "input_acquisitions": input_acquisitions,
            "session_map": session_map_serializable
        })
    `);

    const parsedMapping = JSON.parse(mappingOutput);
    displayMappingUI(parsedMapping);

    fmCheck_btnGenCompliance.textContent = "Generate Compliance Report";
    fmCheck_btnGenCompliance.disabled = false;
}

function displayMappingUI(mappingData) {
    const { reference_acquisitions, input_acquisitions, session_map } = mappingData;

    const mappingContainer = document.getElementById("tableOutput");
    mappingContainer.innerHTML = "";

    const table = document.createElement("table");
    table.innerHTML = `<tr><th>Reference Acquisition/Series</th><th>Input Acquisition/Series</th></tr>`;

    Object.entries(reference_acquisitions).forEach(([refAcqKey, refAcqValue]) => {
        const refSeriesList = refAcqValue.series || [{ name: refAcqKey }];

        refSeriesList.forEach(refSeries => {
            const refSeriesKey = refSeries.name ? `${refAcqKey}::${refSeries.name}` : refAcqKey;
            const row = document.createElement("tr");

            const referenceCell = document.createElement("td");
            referenceCell.textContent = refSeries.name ? `${refAcqKey} - ${refSeries.name}` : refAcqKey;
            row.appendChild(referenceCell);

            const inputCell = document.createElement("td");
            const select = document.createElement("select");
            select.classList.add("mapping-dropdown");
            select.setAttribute("data-reference-key", refSeriesKey);

            const unmappedOption = document.createElement("option");
            unmappedOption.value = "unmapped";
            unmappedOption.textContent = "Unmapped";
            select.appendChild(unmappedOption);

            input_acquisitions.forEach(inputAcq => {
                const option = document.createElement("option");
                option.value = inputAcq;
                option.textContent = inputAcq;

                if (session_map[refSeriesKey] === inputAcq) {
                    option.selected = true;
                }

                select.appendChild(option);
            });

            inputCell.appendChild(select);
            row.appendChild(inputCell);

            table.appendChild(row);
        });
    });

    mappingContainer.appendChild(table);

    const finalizeButton = document.createElement("button");
    finalizeButton.textContent = "Finalize Mapping";
    finalizeButton.onclick = finalizeMapping;
    mappingContainer.appendChild(finalizeButton);
}

async function finalizeMapping() {
    const dropdownMappings = {};
    const dropdowns = document.querySelectorAll(".mapping-dropdown");

    dropdowns.forEach(dropdown => {
        const refKey = dropdown.dataset.referenceKey;
        const inputKey = dropdown.value;

        if (refKey && inputKey && inputKey !== "unmapped") {
            dropdownMappings[refKey] = inputKey;
        }
    });

    const finalizedMapping = JSON.stringify(dropdownMappings);
    pyodide.globals.set("finalized_mapping", finalizedMapping);

    const complianceOutput = await pyodide.runPythonAsync(`
        import json
        from dicompare.compliance import check_session_compliance_with_json_reference, check_session_compliance_with_python_module

        if is_json:
            series_map = {
                tuple(k.split("::")): tuple(v.split("::"))
                for k, v in json.loads(finalized_mapping).items()
            }
            compliance_summary = check_session_compliance_with_json_reference(
                in_session=in_session, ref_session=ref_session, session_map=series_map
            )
        else:
            acquisition_map = {
                k.split("::")[0]: v
                for k, v in json.loads(finalized_mapping).items()
            }
            compliance_summary = check_session_compliance_with_python_module(
                in_session=in_session, ref_models=ref_models, session_map=acquisition_map
            )

        json.dumps(compliance_summary)
    `);

    displayComplianceReport(JSON.parse(complianceOutput));
}

function displayComplianceReport(complianceData) {
    const messageContainer = document.getElementById("fmCheck_outputMessage");
    const tableContainer = document.getElementById("tableOutput");

    if (complianceData.length === 0) {
        messageContainer.textContent = "The input DICOMs are fully compliant with the reference.";
        tableContainer.innerHTML = "";
    } else {
        displayTable(complianceData);
    }
}

function displayTable(parsedOutput) {
    const tableContainer = document.getElementById("tableOutput");
    tableContainer.innerHTML = "";

    if (!Array.isArray(parsedOutput) || parsedOutput.length === 0) {
        console.error("Invalid table data:", parsedOutput);
        tableContainer.innerHTML = "<p>Error: No data to display.</p>";
        return;
    }

    const table = document.createElement("table");
    const headerRow = document.createElement("tr");

    const headers = Object.keys(parsedOutput[0]);
    headers.forEach(header => {
        const th = document.createElement("th");
        th.textContent = header;
        headerRow.appendChild(th);
    });
    table.appendChild(headerRow);

    parsedOutput.forEach(rowData => {
        const row = document.createElement("tr");
        headers.forEach(header => {
            const cell = document.createElement("td");
            if (header === "value") {
                // Parse JSON string for value if necessary
                const value = typeof rowData[header] === "string" ? JSON.parse(rowData[header]) : rowData[header];
                cell.textContent = JSON.stringify(value, null, 2);  // Pretty-print object values
            } else {
                cell.textContent = rowData[header] || "";
            }
            row.appendChild(cell);
        });
        table.appendChild(row);
    });

    tableContainer.appendChild(table);
}

function fmCheck_ValidateForm() {
    const fmCheck_selectDICOMs = document.getElementById("fmCheck_selectDICOMs");
    const fmCheck_selectJsonReference = document.getElementById("fmCheck_selectJsonReference");

    if (fmCheck_selectDICOMs.files.length > 0 && fmCheck_selectJsonReference.files.length > 0) {
        fmCheck_btnGenCompliance.disabled = false;
    } else {
        fmCheck_btnGenCompliance.disabled = true;
    }

    return fmCheck_btnGenCompliance.disabled;
}

document.getElementById("fmCheck_selectDICOMs").addEventListener("change", () => {
    fmCheck_ValidateForm();
});

document.getElementById("fmCheck_selectJsonReference").addEventListener("change", () => {
    fmCheck_ValidateForm();
});

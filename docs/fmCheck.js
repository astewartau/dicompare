let generatedReportData = null;
const fmCheck_btnGenCompliance = document.getElementById("fmCheck_btnGenCompliance");

async function fmCheck_generateComplianceReport() {
    fmCheck_btnGenCompliance.disabled = true;

    if (!pyodide) {
        fmCheck_btnGenCompliance.textContent = "Loading Pyodide...";
        pyodide = await initPyodide(); // Call the corrected initialization function
    }

    fmCheck_btnGenCompliance.textContent = "Loading DICOMs...";
    const dicomFiles = await loadDICOMs("fmCheck_selectDICOMs");

    const jsonReferenceFile = document.getElementById("fmCheck_selectJsonReference").files[0];
    const jsonRefContent = await jsonReferenceFile.text();

    // Pass data to Pyodide's Python environment
    pyodide.globals.set("json_ref", jsonRefContent);
    pyodide.globals.set("dicom_files", dicomFiles);

    fmCheck_btnGenCompliance.textContent = "Generating initial mapping...";

    // Get the initial mapping and reference data
    const mappingOutput = await pyodide.runPythonAsync(`
        import json
        from dcm_check import read_dicom_session, read_json_session, map_session

        # Save the JSON reference content to a file
        with open("temp_json_ref.json", "w") as f:
            f.write(json_ref)

        # Load the JSON reference file
        acquisition_fields, reference_fields, ref_session = read_json_session("temp_json_ref.json")
        in_session = read_dicom_session(dicom_bytes=dicom_files, acquisition_fields=acquisition_fields, reference_fields=reference_fields)
        session_map = map_session(in_session, ref_session)

        # Convert tuple keys in session_map to strings for JSON serialization
        session_map_serializable = {
            f"{key[0]}::{key[1]}": f"{value[0]}::{value[1]}"
            for key, value in session_map.items()
        }

        json.dumps({
            "reference_acquisitions": ref_session["acquisitions"],
            "input_acquisitions": in_session["acquisitions"],
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
    mappingContainer.innerHTML = ""; // Clear any previous mapping UI

    const table = document.createElement("table");
    table.innerHTML = `<tr><th>Reference Acquisition-Series</th><th>Input Acquisition-Series</th></tr>`;

    Object.entries(reference_acquisitions).forEach(([refAcqKey, refAcqValue]) => {
        refAcqValue.series.forEach(refSeries => {
            const refSeriesKey = `${refAcqKey}::${refSeries.name}`;
            const row = document.createElement("tr");

            const referenceCell = document.createElement("td");
            referenceCell.textContent = `${refAcqKey} - ${refSeries.name}`;
            row.appendChild(referenceCell);

            const inputCell = document.createElement("td");
            const select = document.createElement("select");
            select.classList.add("mapping-dropdown"); // Add the class
            select.setAttribute("data-reference-key", refSeriesKey); // Add the data attribute

            const unmappedOption = document.createElement("option");
            unmappedOption.value = "unmapped";
            unmappedOption.textContent = "Unmapped";
            select.appendChild(unmappedOption);

            Object.entries(input_acquisitions).forEach(([inputAcqKey, inputAcqValue]) => {
                inputAcqValue.series.forEach(inputSeries => {
                    const inputSeriesKey = `${inputAcqKey}::${inputSeries.name}`;
                    const option = document.createElement("option");
                    option.value = inputSeriesKey;
                    option.textContent = `${inputAcqKey} - ${inputSeries.name}`;

                    // Pre-select the mapped input acquisition-series if available
                    if (session_map[refSeriesKey] === inputSeriesKey) {
                        option.selected = true;
                    }

                    select.appendChild(option);
                });
            });

            inputCell.appendChild(select);
            row.appendChild(inputCell);

            table.appendChild(row);
        });
    });

    mappingContainer.appendChild(table);

    // Add a button to finalize the mapping
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

    // Pass to Pyodide
    const finalizedMapping = JSON.stringify(dropdownMappings);
    pyodide.globals.set("finalized_mapping", finalizedMapping);

    const complianceOutput = await pyodide.runPythonAsync(`
    import json
    from dcm_check.compliance import check_session_compliance
    from dcm_check import load_ref_dict

    ref_session = load_ref_dict(ref_session)
    
    # Deserialize the mapping
    series_map = {
        tuple(k.split("::")): tuple(v.split("::"))
        for k, v in json.loads(finalized_mapping).items()
    }

    print("series_map", series_map)
    print("ref_session", ref_session)
    print("in_session", in_session)

    # Perform compliance check
    compliance_summary = check_session_compliance(in_session=in_session, ref_session=ref_session, series_map=series_map)

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
        messageContainer.textContent = "The input DICOMs are non-compliant with the reference. The following issues were identified:";
        displayTable(complianceData);
    }
}

function displayTable(parsedOutput) {
    const tableContainer = document.getElementById("tableOutput");
    tableContainer.innerHTML = ""; // Clear any previous table

    if (!Array.isArray(parsedOutput) || parsedOutput.length === 0) {
        console.error("Invalid table data:", parsedOutput);
        tableContainer.innerHTML = "<p>Error: No data to display.</p>";
        return;
    }

    const table = document.createElement("table");
    const headerRow = document.createElement("tr");

    // Dynamically get column headers from the keys of the first object
    const headers = Object.keys(parsedOutput[0]);
    headers.forEach(header => {
        const th = document.createElement("th");
        th.textContent = header;
        headerRow.appendChild(th);
    });
    table.appendChild(headerRow);

    // Populate table rows with the compliance data
    parsedOutput.forEach(rowData => {
        const row = document.createElement("tr");
        headers.forEach(header => {
            const cell = document.createElement("td");
            cell.textContent = rowData[header] || ""; // Fill cell with the value or empty string
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

// disable Generate JSON Reference button if no DICOM files are selected
document.getElementById("fmCheck_selectDICOMs").addEventListener("change", () => {
    fmCheck_ValidateForm();
});

document.getElementById("fmCheck_selectJsonReference").addEventListener("change", () => {
    fmCheck_ValidateForm();
});

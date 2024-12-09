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

    const referenceFile = document.getElementById("fmCheck_selectJsonReference").files[0];
    const referenceFileContent = await referenceFile.text();

    // Pass data to Pyodide's Python environment
    pyodide.globals.set("ref_json_py", referenceFileContent);
    pyodide.globals.set("dicom_files", dicomFiles);

    fmCheck_btnGenCompliance.textContent = "Generating initial mapping...";

    // Get the initial mapping and reference data
    const mappingOutput = await pyodide.runPythonAsync(`
        import json
        from dicompare import read_dicom_session, read_json_session, map_session, load_python_module

        is_json = True
        try:
            json.loads(ref_json_py)
        except json.JSONDecodeError:
            is_json = False
        
        if is_json:
            # Save the JSON reference content to a file
            with open("temp_json_ref.json", "w") as f:
                f.write(ref_json_py)
        else:
            # Save as .py file
            with open("temp_py_ref.py", "w") as f:
                f.write(ref_json_py)

        # Load the JSON reference file
        if is_json:
            acquisition_fields, reference_fields, ref_session = read_json_session(json_ref="temp_json_ref.json")
        else:
            acquisition_fields, reference_fields, ref_models = load_python_module(module_path="temp_py_ref.py")
            ref_model_names = list(ref_models.keys())
            ref_session = {"acquisitions": { ref_model_name: {} for ref_model_name in ref_model_names }}

        print(f"acquisition_fields: {acquisition_fields}")
        print(f"reference_fields: {reference_fields}")

        in_session = read_dicom_session(dicom_bytes=dicom_files, acquisition_fields=acquisition_fields, reference_fields=reference_fields)
        
        if is_json:
            session_map = map_session(in_session, ref_session)

            # Convert tuple keys in session_map to strings for JSON serialization
            session_map_serializable = {
                f"{key[0]}::{key[1]}": f"{value[0]}::{value[1]}"
                for key, value in session_map.items()
            }
        else:
            session_map_serializable = {}

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
    table.innerHTML = `<tr><th>Reference Acquisition/Series</th><th>Input Acquisition/Series</th></tr>`;

    Object.entries(reference_acquisitions).forEach(([refAcqKey, refAcqValue]) => {
        // Check if the reference acquisition has series
        const refSeriesExists = Array.isArray(refAcqValue.series);
        // use name of the acquisition if no series
        const refSeriesList = refSeriesExists ? refAcqValue.series : [{ name: refAcqKey }]; // Use series if defined, otherwise fallback to acquisition-level

        refSeriesList.forEach(refSeries => {
            const refSeriesKey = refSeries.name ? `${refAcqKey}::${refSeries.name}` : refAcqKey;
            const row = document.createElement("tr");

            const referenceCell = document.createElement("td");
            referenceCell.textContent = refSeries.name ? `${refAcqKey} - ${refSeries.name}` : refAcqKey;
            row.appendChild(referenceCell);

            const inputCell = document.createElement("td");
            const select = document.createElement("select");
            select.classList.add("mapping-dropdown"); // Add the class
            select.setAttribute("data-reference-key", refSeriesKey); // Add the data attribute

            const unmappedOption = document.createElement("option");
            unmappedOption.value = "unmapped";
            unmappedOption.textContent = "Unmapped";
            select.appendChild(unmappedOption);

            // Iterate over input acquisitions
            Object.entries(input_acquisitions).forEach(([inputAcqKey, inputAcqValue]) => {
                // If reference has no series, only map acquisition to acquisition
                const inputSeriesList = refSeriesExists && inputAcqValue.series ? inputAcqValue.series : [{ name: inputAcqKey }];
                inputSeriesList.forEach(inputSeries => {
                    // Use series-level mapping only if the reference has series
                    const inputSeriesKey = refSeriesExists && inputSeries.name
                        ? `${inputAcqKey}::${inputSeries.name}`
                        : inputAcqKey;

                    const option = document.createElement("option");
                    option.value = inputSeriesKey;
                    option.textContent = inputSeries.name ? `${inputAcqKey} - ${inputSeries.name}` : inputAcqKey;

                    // Pre-select the mapped input acquisition/series if available
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
    from dicompare.compliance import check_session_compliance, check_session_compliance_python_module

    # Deserialize the mapping
    if is_json:
        series_map = {
            tuple(k.split("::")): tuple(v.split("::"))
            for k, v in json.loads(finalized_mapping).items()
        }
    else:
        # this time we don't want tuples, just a dict mapping the strings
        series_map = {
            k.split("::")[0]: v
            for k, v in json.loads(finalized_mapping).items()
        }

    # Perform compliance check
    if is_json:
        compliance_summary = check_session_compliance(in_session=in_session, ref_session=ref_session, series_map=series_map)
    else:
        compliance_summary = check_session_compliance_python_module(
            in_session=in_session,
            ref_models=ref_models,
            acquisition_map=series_map
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

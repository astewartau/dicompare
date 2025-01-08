// JavaScript code to handle dynamic behavior based on domain selection

const fmCheck_selectDomainReference = document.getElementById("fmCheck_selectDomainReference");
const fmCheck_selectJsonReference = document.getElementById("fmCheck_selectJsonReference");
const fmCheck_btnGenCompliance = document.getElementById("fmCheck_btnGenCompliance");
const fmCheck_outputMessage = document.getElementById("fmCheck_outputMessage");
const tableOutput = document.getElementById("fmCheck_tableOutput");
//const qsm_ref = "http://localhost:8000/dicompare/tests/fixtures/ref_qsm.py";
const qsm_ref = "https://raw.githubusercontent.com/astewartau/dicompare/v0.1.12/dicompare/tests/fixtures/ref_qsm.py";

let generatedReportData = null;
let referenceFilePath = null;

async function fetchReferenceFile(url) {
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`Failed to fetch reference file from ${url}`);
        }
        return await response.text();
    } catch (error) {
        console.error(error);
        addMessage("fmCheck_messages", error.message, "error", "Error fetching reference file");
        return null;
    }
}

async function fmCheck_generateComplianceReport() {
    fmCheck_btnGenCompliance.disabled = true;
    resetMessages("fmCheck_messages");

    if (!pyodide) {
        fmCheck_btnGenCompliance.textContent = "Loading Pyodide...";
        try {
            pyodide = await initPyodide();
        } catch (error) {
            addMessage("fmCheck_messages", error.message, "error", "Error loading Pyodide");
            fmCheck_ValidateForm();
            return;
        }
    }

    if (!referenceFilePath || !referenceFilePath.content) {
        // first attempt to load the reference file
        if (fmCheck_selectJsonReference.files.length > 0) {
            referenceFilePath = {
                name: fmCheck_selectJsonReference.files[0].name,
                content: await fmCheck_selectJsonReference.files[0].text(),
            };
        } else {
            addMessage("fmCheck_messages", "Reference file content is missing. Please ensure a valid reference is selected.", "error");
            fmCheck_ValidateForm();
            return;
        }
    }
    pyodide.FS.writeFile(referenceFilePath.name, referenceFilePath.content);

    fmCheck_btnGenCompliance.textContent = "Loading DICOMs...";
    const dicomFiles = await loadDICOMs("fmCheck_selectDICOMs");

    fmCheck_btnGenCompliance.textContent = "Generating initial mapping...";

    pyodide.globals.set("dicom_files", dicomFiles);
    pyodide.globals.set("is_json", referenceFilePath.name.endsWith(".json"));
    pyodide.globals.set("ref_path", referenceFilePath.name);

    try {
        const mappingOutput = await pyodide.runPythonAsync(`
            import json
            from dicompare.io import load_json_session, load_python_session, load_dicom_session
            from dicompare.mapping import map_to_json_reference
        
            # Load the reference and input sessions
            if is_json:
                reference_fields, ref_session = load_json_session(json_ref=ref_path)
            else:
                ref_models = load_python_session(module_path=ref_path)
                ref_session = {"acquisitions": {k: {} for k in ref_models.keys()}}
            acquisition_fields = ["ProtocolName"]
            
            in_session = load_dicom_session(
                dicom_bytes=dicom_files,
                acquisition_fields=acquisition_fields
            )
            if in_session is None:
                raise ValueError("Failed to load the DICOM session. Ensure the input data is valid.")
            if in_session.empty:
                raise ValueError("The DICOM session is empty. Ensure the input data is correct.")

            input_acquisitions = list(in_session['Acquisition'].unique())
            
            if is_json:
                in_session = in_session.reset_index(drop=True)

                in_session["Series"] = (
                    in_session.groupby(acquisition_fields).apply(
                        lambda group: group.groupby(reference_fields, dropna=False).ngroup().add(1)
                    ).reset_index(level=0, drop=True)  # Reset multi-index back to DataFrame
                ).apply(lambda x: f"Series {x}")
                in_session.sort_values(by=["Acquisition", "Series"] + acquisition_fields + reference_fields, inplace=True)

                missing_fields = [field for field in reference_fields if field not in in_session.columns]
                if missing_fields:
                    raise ValueError(f"Input session is missing required reference fields: {missing_fields}")
                
                session_map = map_to_json_reference(in_session, ref_session)
                session_map_serializable = {
                    f"{key[0]}::{key[1]}": f"{value[0]}::{value[1]}"
                    for key, value in session_map.items()
                }
                # print session map
                print(json.dumps(session_map_serializable, indent=2))
            else:
                # Map acquisitions directly for Python references
                session_map_serializable = {
                    acquisition: ref
                    for acquisition, ref in zip(input_acquisitions, ref_session["acquisitions"])
                }
        
            json.dumps({
                "reference_acquisitions": ref_session["acquisitions"],
                "input_acquisitions": input_acquisitions,
                "session_map": session_map_serializable
            })
        `);

        const parsedMapping = JSON.parse(mappingOutput);
        displayMappingUI(parsedMapping);
    } catch (error) {
        addMessage("fmCheck_messages", error.message, "error", "Error generating compliance report");
    }

    fmCheck_btnGenCompliance.textContent = "Generate compliance report";
    fmCheck_ValidateForm();
}


function fmCheck_handleDomainReferenceChange() {
    const selectedDomain = fmCheck_selectDomainReference.value;
    fmCheck_selectJsonReference.parentElement.style.display = selectedDomain === "Custom" ? "grid" : "none";

    if (selectedDomain === "QSM") {
        fetchReferenceFile(qsm_ref).then((fileContent) => {
            if (fileContent) {
                referenceFilePath = { name: "qsm.py", content: fileContent };
            } else {
                referenceFilePath = null;
                addMessage("fmCheck_messages", "Failed to load QSM reference file.", "error");
                fmCheck_selectDomainReference.value = "Custom";
            }
            fmCheck_ValidateForm();
        });
    } else if (selectedDomain === "Custom") {
        referenceFilePath = null;
    } else {
        referenceFilePath = null;
    }

    fmCheck_ValidateForm();
}

function displayMappingUI(mappingData) {
    const { reference_acquisitions, input_acquisitions, session_map } = mappingData;

    const mappingContainer = document.getElementById("fmCheck_tableOutput");
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

            Object.entries(session_map).forEach(([mapped_input, mapped_reference]) => {
                mapped_input_acquisition = mapped_input.split("::")[0];
                mapped_input_series = mapped_input.split("::")[1];
                mapped_reference_acquisition = mapped_reference.split("::")[0];
                mapped_reference_series = mapped_reference.split("::")[1];

                const option = document.createElement("option");
                option.value = mapped_input;
                option.textContent = mapped_input;

                if (mapped_reference_acquisition === refAcqKey && mapped_reference_series === refSeries.name) {
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

    // Check if "fmCheck_btnNextAction" exists
    let fmCheck_finalizeMapping = document.getElementById("fmCheck_finalizeMapping");
    if (!fmCheck_finalizeMapping) {
        // Create the button if it doesn't exist
        fmCheck_finalizeMapping = document.createElement("button");
        fmCheck_finalizeMapping.id = "fmCheck_finalizeMapping";
        fmCheck_finalizeMapping.classList.add("green");
        fmCheck_finalizeMapping.style.gridColumn = "span 2";
    }

    // Update the button properties
    fmCheck_finalizeMapping.textContent = "Finalize mapping";
    fmCheck_finalizeMapping.onclick = async () => {
        await finalizeMapping(mappingData);
    };

    // Append to fmCheck_buttonRowStart if the button is not already there
    const buttonRow = document.getElementById("fmCheck_buttonRowEnd");
    buttonRow.appendChild(fmCheck_finalizeMapping);
}

async function finalizeMapping(mappingData) {
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

    const fmCheck_finalizeMapping = document.getElementById("fmCheck_finalizeMapping");
    fmCheck_finalizeMapping.remove();

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

    const complianceData = JSON.parse(complianceOutput);
    displayComplianceReport(complianceData);

    // Create "Download compliance summary" button
    const buttonRow = document.getElementById("fmCheck_buttonRowMiddle");
    const button = document.createElement("button");
    button.classList.add("green");
    button.style.gridColumn = "span 2";
    buttonRow.appendChild(button);
    button.textContent = "Download compliance summary";
    button.onclick = () => downloadComplianceSummary(complianceData);
}

function displayComplianceReport(complianceData) {
    const tableContainer = document.getElementById("tableOutput");
    const afterTableContainer = document.getElementById("afterTable");

    // Clear any previous content in the afterTable container
    afterTableContainer.innerHTML = "";

    if (complianceData.length === 0) {
        addMessage("fmCheck_messages", "The input DICOMs are fully compliant with the reference.", "info");
        tableContainer.innerHTML = "";
    } else {
        displayTable(complianceData);
    }
}

function displayTable(parsedOutput) {
    const tableContainer = document.getElementById("fmCheck_tableOutput");
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
                try {
                    const value = typeof rowData[header] === "string" ? JSON.parse(rowData[header]) : rowData[header];
                    cell.textContent = JSON.stringify(value, null, 2);  // Pretty-print object values
                } catch (error) {
                    cell.textContent = rowData[header] || "";
                }
            } else {
                cell.textContent = rowData[header] || "";
            }
            row.appendChild(cell);
        });
        table.appendChild(row);
    });

    tableContainer.appendChild(table);
}

function downloadComplianceSummary(complianceData) {
    const summary = complianceData.map(entry => ({
        acquisition: entry.acquisition || "",
        field: entry.field || "",
        value: entry.value || "",
        rule: entry.rule || "",
        message: entry.message || "",
        passed: entry.passed !== undefined ? entry.passed : null,
    }));

    const blob = new Blob([JSON.stringify(summary, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");
    link.href = url;
    link.download = "compliance_summary.json";
    link.click();

    // Clean up the URL object after download
    URL.revokeObjectURL(url);
}

function fmCheck_ValidateForm() {
    const fmCheck_selectDICOMs = document.getElementById("fmCheck_selectDICOMs");
    const referenceFileSelected = referenceFilePath || (fmCheck_selectJsonReference.files.length > 0 && fmCheck_selectDomainReference.value === "Custom");
    
    fmCheck_btnGenCompliance.textContent = "Generate compliance report";
    if (fmCheck_selectDICOMs.files.length > 0 && referenceFileSelected) {
        fmCheck_btnGenCompliance.disabled = false;
    } else {
        fmCheck_btnGenCompliance.disabled = true;
    }
}

document.getElementById("fmCheck_selectDICOMs").addEventListener("change", () => {
    fmCheck_ValidateForm();
});

document.getElementById("fmCheck_selectJsonReference").addEventListener("change", () => {
    fmCheck_ValidateForm();
});

// Event listeners
fmCheck_selectDomainReference.addEventListener("change", fmCheck_handleDomainReferenceChange);
document.getElementById("fmCheck_selectDICOMs").addEventListener("change", fmCheck_ValidateForm);
document.getElementById("fmCheck_selectJsonReference").addEventListener("change", async () => {
    const file = fmCheck_selectJsonReference.files[0];
    if (file) {
        referenceFilePath = {
            name: file.name,
            content: await file.text(), // Read file content asynchronously
        };
    } else {
        referenceFilePath = null;
    }
    fmCheck_ValidateForm();
});

// make it so when the page loads we run fmCheck_handleDomainReferenceChange()
document.addEventListener("DOMContentLoaded", fmCheck_handleDomainReferenceChange);


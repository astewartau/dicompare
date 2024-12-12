// JavaScript code to handle dynamic behavior based on domain selection

const fmCheck_selectDomainReference = document.getElementById("fmCheck_selectDomainReference");
const fmCheck_selectJsonReference = document.getElementById("fmCheck_selectJsonReference");
const fmCheck_btnGenCompliance = document.getElementById("fmCheck_btnGenCompliance");
const fmCheck_outputMessage = document.getElementById("fmCheck_outputMessage");
const tableOutput = document.getElementById("tableOutput");
const qsm_ref = "http://localhost:8000/dicompare/tests/fixtures/ref_qsm.py";

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
        fmCheck_outputMessage.textContent = `Error fetching reference file: ${error.message}`;
        return null;
    }
}

async function fmCheck_generateComplianceReport() {
    fmCheck_btnGenCompliance.disabled = true;
    fmCheck_outputMessage.textContent = "";

    if (!pyodide) {
        fmCheck_btnGenCompliance.textContent = "Loading Pyodide...";
        pyodide = await initPyodide();
    }

    if (!referenceFilePath || !referenceFilePath.content) {
        // first attempt to load the reference file
        if (fmCheck_selectJsonReference.files.length > 0) {
            referenceFilePath = {
                name: fmCheck_selectJsonReference.files[0].name,
                content: await fmCheck_selectJsonReference.files[0].text(),
            };
        } else {
            fmCheck_outputMessage.textContent = "Reference file content is missing. Please ensure a valid reference is selected.";
            fmCheck_btnGenCompliance.disabled = false;
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
                acquisition_fields, reference_fields, ref_session = load_json_session(ref_path)
            else:
                ref_models = load_python_session(module_path=ref_path)
                ref_session = {"acquisitions": {k: {} for k in ref_models.keys()}}
                acquisition_fields = ["ProtocolName"]
        
            in_session = load_dicom_session(
                dicom_bytes=dicom_files,
                acquisition_fields=acquisition_fields
            )
        
            input_acquisitions = list(in_session['Acquisition'].unique())
        
            if is_json:
                in_session = (
                    in_session.groupby(reference_fields)
                    .apply(lambda x: x.reset_index(drop=True))
                    .reset_index(drop=True)
                )
                in_session["Series"] = (
                    in_session.groupby(reference_fields, dropna=False).ngroup().add(1).apply(lambda x: f"Series {x}")
                )

                session_map = map_to_json_reference(in_session, ref_session)
                session_map_serializable = {
                    f"{key[0]}::{key[1]}": f"{value[0]}::{value[1]}"
                    for key, value in session_map.items()
                }

                # print unique combinations of Acquisition and Series
                print(in_session.groupby(["Acquisition", "Series"]).size().reset_index(name="count"))
            else:
                # Map acquisitions directly for Python references
                session_map_serializable = {
                    acquisition: ref
                    for acquisition, ref in zip(input_acquisitions, ref_session["acquisitions"])
                }
        
            print(f"Reference acquisitions: {ref_session['acquisitions']}")
            print(f"Input acquisitions: {input_acquisitions}")
            print(f"Session map: {session_map_serializable}")
        
            json.dumps({
                "reference_acquisitions": ref_session["acquisitions"],
                "input_acquisitions": input_acquisitions,
                "session_map": session_map_serializable
            })
        `);

        const parsedMapping = JSON.parse(mappingOutput);
        displayMappingUI(parsedMapping);
    } catch (error) {
        console.error("Error generating compliance report:", error);
        fmCheck_outputMessage.textContent = "Error generating compliance report: " + error.message;
    }

    fmCheck_btnGenCompliance.textContent = "Generate Compliance Report";
    fmCheck_btnGenCompliance.disabled = false;
}


function fmCheck_handleDomainReferenceChange() {
    const selectedDomain = fmCheck_selectDomainReference.value;
    fmCheck_selectJsonReference.parentElement.style.display = selectedDomain === "Custom" ? "grid" : "none";

    if (selectedDomain === "QSM") {
        fetchReferenceFile(qsm_ref).then((fileContent) => {
            if (fileContent) {
                referenceFilePath = { name: "qsm.py", content: fileContent };
                fmCheck_outputMessage.textContent = "";
            } else {
                referenceFilePath = null;
                fmCheck_outputMessage.textContent = "Failed to load QSM reference file.";
                fmCheck_selectDomainReference.value = "Custom";
            }
            fmCheck_ValidateForm();
        });
    } else if (selectedDomain === "Custom") {
        referenceFilePath = null;
    } else {
        referenceFilePath = null;
        fmCheck_outputMessage.textContent = "";
    }

    fmCheck_ValidateForm();
}

function fmCheck_ValidateForm() {
    const fmCheck_selectDICOMs = document.getElementById("fmCheck_selectDICOMs");
    const referenceFileSelected = referenceFilePath || fmCheck_selectJsonReference.files.length > 0;

    if (fmCheck_selectDICOMs.files.length > 0 && referenceFileSelected) {
        fmCheck_btnGenCompliance.disabled = false;
    } else {
        fmCheck_btnGenCompliance.disabled = true;
    }
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

            // Populate dropdown with acquisition-series pairs
            Object.entries(session_map).forEach(([sessionKey, sessionValue]) => {
                const option = document.createElement("option");
                option.value = sessionKey;
                option.textContent = sessionKey;

                if (session_map[refSeriesKey] === sessionValue) {
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
    finalizeButton.classList.add("green");
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
    const afterTableContainer = document.getElementById("afterTable");

    // Clear any previous content in the afterTable container
    afterTableContainer.innerHTML = "";

    if (complianceData.length === 0) {
        messageContainer.textContent = "The input DICOMs are fully compliant with the reference.";
        tableContainer.innerHTML = "";
    } else {
        displayTable(complianceData);

        // Add the "Download compliance summary" button
        const downloadButton = document.createElement("button");
        downloadButton.textContent = "Download compliance summary";
        downloadButton.classList.add("green"); // Assign the "green" class
        downloadButton.onclick = () => downloadComplianceSummary(complianceData);

        // Append the button to the afterTable container
        afterTableContainer.appendChild(downloadButton);
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


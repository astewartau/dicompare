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

    fmCheck_btnGenCompliance.textContent = "Generating compliance report...";

    const output = await pyodide.runPythonAsync(`
    import json
    import pandas as pd
    from dcm_check import load_ref_dict, read_dicom_session, read_json_session, check_session_compliance, map_session, interactive_mapping

    # Save the JSON reference content to a file
    with open("temp_json_ref.json", "w") as f:
        f.write(json_ref)

    # Load the JSON reference file
    acquisition_fields, reference_fields, ref_session = read_json_session("temp_json_ref.json")
    ref_session = load_ref_dict(ref_session)
    in_session = read_dicom_session(dicom_bytes=dicom_files, acquisition_fields=acquisition_fields, reference_fields=reference_fields)
    session_map = map_session(in_session, ref_session)

    compliance_summary = check_session_compliance(in_session, ref_session, session_map)
    
    compliance_df = pd.DataFrame(compliance_summary)
    
    if compliance_df.empty:
        output = json.dumps({"empty": True})
    else:
        output = compliance_df.to_json(orient="split")

    output
  `);

    fmCheck_btnGenCompliance.textContent = "Parsing and Displaying Report...";
    const parsedOutput = JSON.parse(output);

    // Determine if the report is empty
    const messageContainer = document.getElementById("fmCheck_outputMessage");
    if (parsedOutput.empty) {
        messageContainer.textContent = "The input DICOMs are fully compliant with the reference.";
    } else {
        messageContainer.textContent = "The input DICOMs are non-compliant with the reference. The following issues were identified:";
        displayTable(parsedOutput);
    }

    fmCheck_btnGenCompliance.textContent = "Generate Compliance Report";
    fmCheck_btnGenCompliance.disabled = false;
}

function displayTable(parsedOutput) {
    const tableContainer = document.getElementById("tableOutput");
    tableContainer.innerHTML = "";  // Clear any previous table

    const table = document.createElement("table");
    const headerRow = document.createElement("tr");

    // Get column headers from the DataFrame structure
    const headers = parsedOutput.columns;
    headers.forEach(header => {
        const th = document.createElement("th");
        th.textContent = header;
        headerRow.appendChild(th);
    });
    table.appendChild(headerRow);

    // Populate table rows with the compliance data
    parsedOutput.data.forEach(rowData => {
        const row = document.createElement("tr");
        rowData.forEach(cellData => {
            const cell = document.createElement("td");
            cell.textContent = cellData;
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

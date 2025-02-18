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
                dicom_bytes=dicom_files.to_py(),
                acquisition_fields=acquisition_fields
            )
            print("Loaded input session")

            if in_session is None:
                raise ValueError("Failed to load the DICOM session. Ensure the input data is valid.")
            if in_session.empty:
                raise ValueError("The DICOM session is empty. Ensure the input data is correct.")

            input_acquisitions = list(in_session['Acquisition'].unique())
            
            if is_json:
                in_session = in_session.reset_index(drop=True)
                in_session.sort_values(by=["Acquisition"] + acquisition_fields + reference_fields, inplace=True)
                session_map = map_to_json_reference(in_session, ref_session)
                print(json.dumps(session_map, indent=2))
            else:
                # Direct mapping for Python references
                session_map = {
                    acquisition: ref
                    for acquisition, ref in zip(input_acquisitions, ref_session["acquisitions"])
                }
        
            json.dumps({
                "reference_acquisitions": ref_session["acquisitions"],
                "input_acquisitions": input_acquisitions,
                "session_map": session_map
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
    table.innerHTML = `<tr><th>Reference Acquisition</th><th>Input Acquisition</th></tr>`;

    // One row per reference acquisition
    for (const refAcqName in reference_acquisitions) {
        const row = document.createElement("tr");

        const referenceCell = document.createElement("td");
        referenceCell.textContent = refAcqName;
        row.appendChild(referenceCell);

        const inputCell = document.createElement("td");
        const select = document.createElement("select");
        select.classList.add("mapping-dropdown");
        select.setAttribute("data-reference-key", refAcqName);

        const unmappedOption = document.createElement("option");
        unmappedOption.value = "unmapped";
        unmappedOption.textContent = "Unmapped";
        select.appendChild(unmappedOption);

        // Populate the dropdown with input acquisitions
        input_acquisitions.forEach(inAcq => {
            const option = document.createElement("option");
            option.value = inAcq;
            option.textContent = inAcq;
            if (session_map[refAcqName] === inAcq) {
                option.selected = true;
            }
            select.appendChild(option);
        });

        inputCell.appendChild(select);
        row.appendChild(inputCell);
        table.appendChild(row);
    }

    mappingContainer.appendChild(table);

    let fmCheck_finalizeMapping = document.getElementById("fmCheck_finalizeMapping");
    if (!fmCheck_finalizeMapping) {
        fmCheck_finalizeMapping = document.createElement("button");
        fmCheck_finalizeMapping.id = "fmCheck_finalizeMapping";
        fmCheck_finalizeMapping.classList.add("green");
        fmCheck_finalizeMapping.style.gridColumn = "span 2";
    }

    fmCheck_finalizeMapping.textContent = "Finalize mapping";
    fmCheck_finalizeMapping.onclick = async () => {
        await finalizeMapping(mappingData);
    };

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
            acquisition_map = json.loads(finalized_mapping)
            compliance_summary = check_session_compliance_with_json_reference(
                in_session=in_session, ref_session=ref_session, session_map=acquisition_map
            )
        else:
            acquisition_map = json.loads(finalized_mapping)
            compliance_summary = check_session_compliance_with_python_module(
                in_session=in_session, ref_models=ref_models, session_map=acquisition_map
            )

        json.dumps(compliance_summary)
    `);

    const complianceData = JSON.parse(complianceOutput);
    displayComplianceReport(complianceData);
    signAndDisplayComplianceReport(complianceData);
}

async function signComplianceReport(complianceData) {
    const metadata = {
        generation_date: new Date().toISOString(),
        compliance_data: complianceData,
    };

    const metadataJson = JSON.stringify(metadata, null, 2);

    // PEM-formatted RSA private key in PKCS#8 format
    const privateKeyPem = `
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCxOhmypqo9KJZ5
RrlMWiyvxfZZes/APZXoIToRy0BFNa2Nc3FCfHZlA2OhbocGy44eJfj2397BjBEv
TK/fmJ+Yi1nEHFHxl+ILGBjGU6GfE//ytspv0brRCzPim1tfSMRjxMqeESa8Qckf
qA3rgMfMkizuVjy76vcuReyubXehj8yAmfhp0kViraRlCmDvFmfM2Q9XZz9mr6tJ
K7lthnd5QdkFoDKw6npQvekaAC0RHsXhU/9oW5Rm/mDkY59TvIfjHNHj/em1Zq3a
3zhIdejRE+S3MovzVXOA1IO1DVczAd5clzrtBpDCPSxjDL/VRffvi5RcIQn3VoYQ
vnSVpc3zAgMBAAECggEABz4pngcjqUYxssPKKi2mlTRmQffmlPkErwI/SPThK92V
ZH+ASchOX7MeF5Mtyir4JDvxtcfREbXeCex8ujWW6CQMchr6L6vBCCpe8NQAJJaA
/PQCx+5upRZryL9dTO1AtsHByhNHXaWOnlA+6WNPnF5TnxXqe3+PGdavuofXaMR8
gDb1mDvp+9pp7n5SzA0WLt0UHk9HoOUH5cdv2S+o9lmBHUDp6kuChjArALN5WzN1
Jg4+XGRnv/lGQEDm90JdWyZ+ddqnpOpjhxGrFXGhcq8E059nqUwLPoNW5JbV4+DQ
cbniwcGOfE30RE3lW7BNW86agc4etcCoQLS7JgdwwQKBgQDuq/uN1fYb95elGQcH
sWUiD4EpFw0pJ2clTV3GxUIAA+XOM6K5lqay7zFICJSeCRuibrv1YX/I14OpDR8v
fXA9jTuaIOIlycMrNxgpR7vR3gfYOcy0rMC4FwUOpudsqeshTf06i69WkDbxJdV1
2sujkFt4MlQMku2dygD9E8un0wKBgQC+GBZjxdUhssxK2Oh+g5LrMk99bLo/hZmx
NGuxidLmtvrKjHe0wfA5yh0I+l8IMkb32FnfBJZDAGQbg55bv95P/UIEBOO9FGKh
sSPq7QhRWgom78FZbES10PukFp38HjmIBW0QUBsloHFra2X3FcBKfA6ogIdz3LZT
/oN+kkSNYQKBgC+fp5k8qVgZRmwOG2YAkrKCL36Yd+rPTviVgHHKKIpCPNexW/X2
RpsLuWSrOaRzIs19lQm4g7v6rO3NjXx3Zi8SAGOXzihGIyh7XNnX03Vj/WK63crr
caUKCttKmIEJQr6phi7pcnouWpgxuW9D0kB37JiGSlkb9Ef458uX6Jo7AoGAG1ov
7o9KyZyGlMZ9PacE/t6wXWXFrto0cTEPxe4E8LmngHmRx+qX/Fi+sMoF3pINcCAr
XlG0pVNrFCJuKNmEzZGtbBKgClbikk2A047jwYDpMQ0SjyFrCZZWfxfaB6r5sD7H
oK9GGLXrW/+KHnF8x7ruCQTleKBrg859cTrurkECgYEAqpAQw11eelM5FNsX8LK+
avj77WxImfDtCJnr8q+D8UJMyWJrVlV2FF8TDGreL7QexlJefdhqFrW22kUPKYqP
LvGkNmEf/brJcfYWJY3okhEZUBXVgpkROv27SFtWY0DhzCSPgeY/aCrDyu6qyydg
4R43e/rEi7P6ZqYdIorGEt4=
-----END PRIVATE KEY-----
    `.trim();

    const privateKeyBinary = Uint8Array.from(
        atob(privateKeyPem.split("\n").slice(1, -1).join("")),
        c => c.charCodeAt(0)
    );

    try {
        const privateKey = await crypto.subtle.importKey(
            "pkcs8",
            privateKeyBinary.buffer,
            { name: "RSA-PSS", hash: "SHA-256" },
            false,
            ["sign"]
        );

        const encoder = new TextEncoder();
        const dataToSign = encoder.encode(metadataJson);
        console.log("Data to be signed:", metadataJson);

        const signature = await crypto.subtle.sign(
            {
                name: "RSA-PSS",
                saltLength: 32,
            },
            privateKey,
            dataToSign
        );

        const base64Signature = btoa(String.fromCharCode(...new Uint8Array(signature)));
        metadata.signature = base64Signature;

        return metadata;
    } catch (error) {
        console.error("Error signing compliance report:", error);
        throw new Error("Failed to sign compliance report.");
    }
}

async function verifyComplianceReport(signedMetadata) {
    const { compliance_data, generation_date, signature, publicKey } = signedMetadata;

    const metadata = {
        generation_date,
        compliance_data,
    };

    const metadataJson = JSON.stringify(metadata, null, 2);

    const publicKeyBuffer = Uint8Array.from(
        atob(publicKey.trim().split("\n").slice(1, -1).join("")),
        c => c.charCodeAt(0)
    );

    const publicKeyObj = await crypto.subtle.importKey(
        "spki",
        publicKeyBuffer,
        { name: "RSA-PSS", hash: "SHA-256" },
        false,
        ["verify"]
    );

    const signatureBuffer = Uint8Array.from(atob(signature), c => c.charCodeAt(0));

    const isValid = await crypto.subtle.verify(
        {
            name: "RSA-PSS",
            saltLength: 32,
        },
        publicKeyObj,
        signatureBuffer,
        new TextEncoder().encode(metadataJson)
    );

    return isValid;
}

function displaySignedComplianceReport(signedMetadata) {
    const buttonRow = document.getElementById("fmCheck_buttonRowEnd");
    const outputContainer = document.getElementById("fmCheck_signedOutput");
    outputContainer.style.display = "block";
    outputContainer.innerHTML = `
        <pre class="badge-box" style="margin: 0;">${JSON.stringify(signedMetadata, null, 4)}</pre>
    `;

    const downloadButton = document.createElement("button");
    downloadButton.textContent = "Download signed report";
    downloadButton.classList.add("green");
    downloadButton.style.marginTop = "20px";

    downloadButton.onclick = () => {
        const blob = new Blob([JSON.stringify(signedMetadata, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);

        const link = document.createElement("a");
        link.href = url;
        link.download = "signed_compliance_report.json";
        link.click();

        URL.revokeObjectURL(url);
    };

    buttonRow.appendChild(downloadButton);
}

async function displayComplianceReport(complianceData) {
    const tableContainer = document.getElementById("fmCheck_tableOutput");
    tableContainer.innerHTML = "";

    if (complianceData.length === 0) {
        addMessage("fmCheck_messages", "The input DICOMs are fully compliant with the reference.", "info");
    } else {
        displayTable(complianceData);
    }
}

async function signAndDisplayComplianceReport(complianceData) {
    try {
        const signedMetadata = await signComplianceReport(complianceData);
        displaySignedComplianceReport(signedMetadata);
    } catch (error) {
        console.error("Error signing compliance report:", error);
        addMessage("fmCheck_messages", error.message, "error", "Failed to sign compliance report");
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
            try {
                const value = typeof rowData[header] === "string" ? JSON.parse(rowData[header]) : rowData[header];
                cell.textContent = JSON.stringify(value, null, 2);
            } catch (error) {
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

fmCheck_selectDomainReference.addEventListener("change", fmCheck_handleDomainReferenceChange);
document.getElementById("fmCheck_selectDICOMs").addEventListener("change", fmCheck_ValidateForm);
document.getElementById("fmCheck_selectJsonReference").addEventListener("change", async () => {
    const file = fmCheck_selectJsonReference.files[0];
    if (file) {
        referenceFilePath = {
            name: file.name,
            content: await file.text(),
        };
    } else {
        referenceFilePath = null;
    }
    fmCheck_ValidateForm();
});

// run fmCheck_handleDomainReferenceChange() when the page loads
document.addEventListener("DOMContentLoaded", fmCheck_handleDomainReferenceChange);


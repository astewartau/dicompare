let dicomData;
let acquisitionData = {};

function arraysEqual(a, b) {
    if (!Array.isArray(a) || !Array.isArray(b)) return false;
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
        if (a[i] !== b[i]) return false;
    }
    return true;
}

function getConstantFields(rows, fields) {
    const constantFields = {};
    const variableFields = [...fields];

    if (!rows.length || !fields.length) {
        return { constantFields, variableFields };
    }

    fields.forEach(field => {
        const firstValue = rows[0][field];

        let isConstant = true;
        for (let i = 0; i < rows.length; i++) {
            const current = rows[i][field];

            // If these are arrays, do array comparison
            if (Array.isArray(firstValue) && Array.isArray(current)) {
                if (!arraysEqual(firstValue, current)) {
                    isConstant = false;
                    break;
                }
            } else {
                // fallback to normal '===' check for strings, numbers, etc.
                if (current !== firstValue) {
                    isConstant = false;
                    break;
                }
            }
        }

        if (isConstant) {
            constantFields[field] = firstValue;
            const idx = variableFields.indexOf(field);
            if (idx !== -1) {
                variableFields.splice(idx, 1);
            }
        }
    });

    return { constantFields, variableFields };
}

async function fetchUniqueRows(acquisition, selectedFields) {
    console.log("Fetching unique rows for acquisition:", acquisition, "with fields:", selectedFields);

    // If no fields, return empty
    if (!selectedFields || selectedFields.length === 0) {
        return [];
    }

    pyodide.globals.set("acquisition", acquisition);
    pyodide.globals.set("selected_fields", selectedFields);

    const rows = await pyodide.runPythonAsync(`
        import json

        df = session_dataframe[session_dataframe['ProtocolName'] == acquisition].copy()

        missing_fields = [f for f in selected_fields if f not in df.columns]
        if missing_fields:
            raise ValueError(f"One or more selected fields are missing in df.columns: {missing_fields}")

        df.columns = df.columns.str.strip()

        def make_hashable(value):
            """Recursively convert lists/dicts to hashable JSON or tuples."""
            if isinstance(value, (list, dict)):
                return json.dumps(value, sort_keys=True)
            elif isinstance(value, (set, tuple)):
                return tuple(make_hashable(v) for v in value)
            return value

        for col in df.columns:
            df[col] = df[col].apply(make_hashable)

        df.drop_duplicates(subset=selected_fields, inplace=True)

        sort_cols = list(set(selected_fields).intersection(df.columns))
        if sort_cols:
            df.sort_values(by=sort_cols, ascending=True, inplace=True)

        df.to_dict(orient='records')
      `).then(res => res.toJs());

    return rows;
}

async function analyzeDicoms() {
    document.getElementById("fmGenRef_analyzeButton").disabled = true;
    document.getElementById("fmGenRef_analyzeButton").textContent = "Loading Pyodide...";

    pyodide = await initPyodide();

    document.getElementById("fmGenRef_analyzeButton").textContent = "Reading DICOMs...";
    const dicom_bytes = await loadDICOMs("fmGenRef_DICOMs");

    document.getElementById("fmGenRef_analyzeButton").textContent = "Analyzing...";
    pyodide.globals.set("dicom_bytes", dicom_bytes);
    try {
        await pyodide.runPythonAsync(`
          from dicompare.io import load_dicom_session
          import pandas as pd

          session = load_dicom_session(
            dicom_bytes=dicom_bytes,
            acquisition_fields=['ProtocolName']
          )
          session = session.reset_index(drop=True)

          global session_dataframe
          session_dataframe = session
        `);

        const acquisitions = await pyodide.runPythonAsync(`
          import json
          json.dumps(session_dataframe['ProtocolName'].unique().tolist())
        `);

        const acquisitionList = JSON.parse(acquisitions);
        displayUniqueAcquisitions(acquisitionList);
        resetMessages("fmGenRef_messages");

        // add button like this programmatically to the fmGenRef_buttonArea div <button id="fmGenRef_saveTemplateButton" onclick="saveTemplate() " class="green" disabled style="grid-column: span 2;">Save Template</button>
        const saveButton = document.createElement("button");
        saveButton.id = "fmGenRef_saveTemplateButton";
        saveButton.textContent = "Save template";
        saveButton.className = "green";
        saveButton.style.gridColumn = "span 2";
        saveButton.onclick = saveTemplate;
        document.getElementById("fmGenRef_buttonArea").appendChild(saveButton);

    } catch (error) {
        addMessage("fmGenRef_messages", error, "error", "Error analyzing DICOMs");
    } finally {
        document.getElementById("fmGenRef_analyzeButton").disabled = false;
        document.getElementById("fmGenRef_analyzeButton").textContent = "Analyze";
    }
}

async function displayUniqueAcquisitions(acquisitionList) {
    console.log("Unique acquisitions:", acquisitionList);
    const container = document.getElementById("fmGenRef_templateEditor");
    container.innerHTML = "";

    // Fetch the valid fields from the pandas dataframe
    let validFields = [];
    try {
        validFields = await pyodide.runPythonAsync(`
            import json
            # Get the column names from the pandas dataframe
            json.dumps(list(session_dataframe.columns))
        `);
        validFields = JSON.parse(validFields); // Convert Python JSON string to JavaScript array
    } catch (error) {
        console.error("Error fetching valid fields:", error);
        validFields = []; // Fallback in case of error
    }

    acquisitionData = {}; // Reset

    acquisitionList.forEach((acquisition, index) => {
        acquisitionData[acquisition] = []; // Initialize data storage for each acquisition

        // Heading
        const heading = document.createElement("h2");
        heading.textContent = `Acquisition ${index + 1}`;
        heading.style.textAlign = "center";
        container.appendChild(heading);

        // Acquisition name row
        const acquisitionNameRow = document.createElement("div");
        acquisitionNameRow.className = "row";

        // label
        const acq_label = document.createElement("label");
        acq_label.textContent = "Acquisition name:";
        acquisitionNameRow.appendChild(acq_label);

        // input 
        const acq_input = document.createElement("input");
        acq_input.type = "text";
        acq_input.placeholder = "Acquisition name";
        acq_input.value = acquisition;
        acquisitionNameRow.appendChild(acq_input);

        // add
        container.appendChild(acquisitionNameRow);

        // Application select row
        const applicationRow = document.createElement("div");
        applicationRow.className = "row";

        // dropdown label
        const applicationLabel = document.createElement("label");
        applicationLabel.textContent = "Application:";
        applicationRow.appendChild(applicationLabel);

        // dropdown
        const applicationDropdown = document.createElement("select");

        // default option
        const defaultOption = document.createElement("option");
        defaultOption.value = "";
        defaultOption.textContent = "-- Select application --";
        applicationDropdown.appendChild(defaultOption);

        // qsm option
        const qsmOption = document.createElement("option");
        qsmOption.value = "qsm";
        qsmOption.textContent = "Quantitative Susceptibility Mapping";
        applicationDropdown.appendChild(qsmOption);

        // option values
        applicationDropdown.addEventListener("change", () => {
            if (applicationDropdown.value === "qsm") {
                // The needed fields for QSM:
                const qsmFields = [
                    "ImageType",
                    "EchoTime",
                    "MRAcquisitionType",
                    "RepetitionTime",
                    "MagneticFieldStrength",
                    "FlipAngle",
                    "PixelSpacing",
                    "SliceThickness",
                    "PixelBandwidth"
                ];
                // Add them to Tagify
                tagifyInstance.addTags(qsmFields);
            }
        });

        // add
        applicationRow.appendChild(applicationDropdown);
        container.appendChild(applicationRow);

        // Validation fields row
        const acquisitionRow = document.createElement("div");
        acquisitionRow.className = "row";

        // tagify label
        const tagifyLabel = document.createElement("label");
        tagifyLabel.textContent = "Validation fields:";
        acquisitionRow.appendChild(tagifyLabel);

        // tagify input
        const input = document.createElement("textarea");
        input.placeholder = "Enter validation fields, e.g., EchoTime";
        acquisitionRow.appendChild(input);

        // set width to 100%
        input.style.width = "100%";

        const tagifyInstance = new Tagify(input, {
            enforceWhitelist: true,
            delimiters: null,
            whitelist: validFields,
            dropdown: { enabled: 0, position: "all" },
        });

        tagifyInstance.on("change", () => {
            const tags = tagifyInstance.value.map(tag => tag.value);
            acquisitionData[acquisition] = tags;
            pyodide.globals.set("selected_fields", tags);
            pyodide.globals.set("current_acquisition", acquisition);
            updateTable(acquisition, tags);
        });

        // combine into container
        const tableContainer = document.createElement("div");
        tableContainer.className = "dynamic-table";
        tableContainer.id = `table-container-${acquisition}`;
        container.appendChild(acquisitionRow);
        container.appendChild(tableContainer);
    });
}


async function updateTable(acquisition, selectedFields) {
    selectedFields.sort();
    console.log("Updating table for acquisition:", acquisition, "with fields:", selectedFields);
    const tableContainerId = `table-container-${acquisition}`;
    const tableContainer = document.getElementById(tableContainerId);
    tableContainer.innerHTML = "";

    if (selectedFields.length === 0) {
        return;
    }

    try {
        const uniqueRows = await pyodide.runPythonAsync(`
          df = session_dataframe[session_dataframe['ProtocolName'] == current_acquisition][selected_fields].drop_duplicates()
          df = df.sort_values(by=list(df.columns))
          if len(df) > 1:
              df.insert(0, 'Series', range(1, len(df) + 1))
          df.to_dict(orient='records')
        `);

        // Convert to JS
        const rows = uniqueRows.toJs();
        const fields = ["Series", ...selectedFields];
        const { constantFields, variableFields } = getConstantFields(rows, fields);

        // Force "Series" out of the constant table
        if ("Series" in constantFields) {
            delete constantFields["Series"];
        }

        // Build the constant fields table
        if (Object.keys(constantFields).length > 0) {
            const constantTable = document.createElement("table");
            constantTable.style.marginBottom = "1em";
            constantTable.style.margin = "0 auto";

            // Header for constant table
            const cHeaderRow = document.createElement("tr");
            const cFieldHeader = document.createElement("th");
            cFieldHeader.textContent = "Field";
            cHeaderRow.appendChild(cFieldHeader);

            const cValueHeader = document.createElement("th");
            cValueHeader.textContent = "Value";
            cHeaderRow.appendChild(cValueHeader);

            constantTable.appendChild(cHeaderRow);

            // Body
            for (const [fieldName, value] of Object.entries(constantFields)) {
                const row = document.createElement("tr");

                // Field name cell
                const nameCell = document.createElement("td");
                nameCell.textContent = fieldName;
                row.appendChild(nameCell);

                // (NEW) Use createValidationCell in the constant table
                const valueCell = document.createElement("td");
                // We'll pass `value` as the initialValue
                // The fieldName might be just for reference, we won't do Series logic here.
                valueCell.appendChild(createValidationCell(fieldName, value, 0));
                row.appendChild(valueCell);

                constantTable.appendChild(row);
            }

            tableContainer.appendChild(constantTable);
        }

        // Now the variable table
        if (variableFields.length > 0) {
            const table = document.createElement("table");
            table.style.margin = "0 auto";
            const tableFields = variableFields.filter(f => f !== "Series");
            const displayFields = ["Series", ...tableFields.filter(f => f !== "Series")];

            // Header row
            const headerRow = document.createElement("tr");
            displayFields.forEach(field => {
                const th = document.createElement("th");
                th.textContent = field;
                headerRow.appendChild(th);
            });

            table.appendChild(headerRow);

            // Body rows
            rows.forEach((rowData, index) => {
                const tr = document.createElement("tr");
                displayFields.forEach(field => {
                    const td = document.createElement("td");
                    if (field === "Series") {
                        // series is single text only
                        const seriesInput = document.createElement("input");
                        seriesInput.type = "text";
                        seriesInput.value = (rowData[field] || (index));
                        td.appendChild(seriesInput);
                    } else {
                        td.appendChild(createValidationCell(field, rowData[field], index));
                    }
                    tr.appendChild(td);
                });
                table.appendChild(tr);
            });

            tableContainer.appendChild(table);

        }
    } catch (error) {
        console.error("Error updating table:", error);
        tableContainer.innerHTML = "<p>Error displaying data.</p>";
    }
}

// Reused from earlier code: the dropdown approach
function createValidationCell(fieldName, initialValue, rowIndex) {
    // Outer container
    const container = document.createElement("div");
    container.style.display = "flex";
    container.style.flexDirection = "column";

    // 1) The dropdown
    const select = document.createElement("select");
    select.innerHTML = `
        <option value="value">Value</option>
        <option value="range">Range</option>
        <option value="tolerance">Value and tolerance</option>
        <option value="contains">Contains</option>
      `;
    container.appendChild(select);

    // 2) The sub-input containers
    const valueInputDiv = document.createElement("div");
    const singleInput = document.createElement("input");
    singleInput.type = "text";
    singleInput.value = initialValue || "";
    singleInput.style.width = "100%";
    valueInputDiv.appendChild(singleInput);

    const rangeInputDiv = document.createElement("div");
    const minInput = document.createElement("input");
    minInput.type = "text";
    minInput.placeholder = "Min";
    minInput.value = initialValue || "";
    minInput.style.width = "50%";
    const maxInput = document.createElement("input");
    maxInput.type = "text";
    maxInput.placeholder = "Max";
    maxInput.style.width = "50%";
    rangeInputDiv.appendChild(minInput);
    rangeInputDiv.appendChild(maxInput);

    const containsInputDiv = document.createElement("div");
    const containsInput = document.createElement("input");
    containsInput.type = "text";
    containsInput.value = initialValue || "";
    containsInput.placeholder = "Must contain...";
    containsInput.style.width = "100%";
    containsInputDiv.appendChild(containsInput);

    const valAndTolInputDiv = document.createElement("div");
    const valInput = document.createElement("input");
    valInput.type = "text";
    valInput.placeholder = "Value";
    valInput.style.width = "50%";
    valInput.value = initialValue || "";
    const tolInput = document.createElement("input");
    tolInput.type = "text";
    tolInput.placeholder = "Tolerance";
    tolInput.value = 0;
    tolInput.style.width = "50%";
    valAndTolInputDiv.appendChild(valInput);
    valAndTolInputDiv.appendChild(tolInput);

    // Classes for easy styling
    valueInputDiv.classList.add("valueInput");
    rangeInputDiv.classList.add("rangeInputs");
    containsInputDiv.classList.add("containsInput");
    valAndTolInputDiv.classList.add("valAndTolInput");

    // Add them to container (all hidden except the first by default)
    container.appendChild(valueInputDiv);
    container.appendChild(rangeInputDiv);
    container.appendChild(containsInputDiv);
    container.appendChild(valAndTolInputDiv);

    // Hide the other ones by default
    rangeInputDiv.style.display = "none";
    containsInputDiv.style.display = "none";
    valAndTolInputDiv.style.display = "none";

    // On select change, show/hide appropriate inputs
    select.addEventListener("change", () => {
        const mode = select.value;
        valueInputDiv.style.display = (mode === "value") ? "block" : "none";
        rangeInputDiv.style.display = (mode === "range") ? "flex" : "none";
        containsInputDiv.style.display = (mode === "contains") ? "block" : "none";
        valAndTolInputDiv.style.display = (mode === "tolerance") ? "flex" : "none";
    });

    return container;
}


function saveTemplate() {
    // This object will hold all acquisitions keyed by their final name
    const acquisitionsObj = {};

    const container = document.getElementById("fmGenRef_templateEditor");

    // Each acquisition block has a heading: <h2>Acquisition #</h2>
    // We'll use these headings to group the subsequent rows & tables.
    const acquisitionHeadings = container.querySelectorAll("h2");

    acquisitionHeadings.forEach((heading) => {
        // The heading for display only (e.g. "Acquisition 1")
        // Next siblings are the .row elements for this block until the next heading or until none remain.
        // We'll gather them in an array until we reach the next <h2> or the end.
        let blockEls = [];
        let currentEl = heading.nextElementSibling;

        while (currentEl && currentEl.tagName !== "H2") {
            blockEls.push(currentEl);
            currentEl = currentEl.nextElementSibling;
        }

        // Now blockEls might look like:
        //   [
        //     <div class="row"> (Acquisition name) </div>,
        //     <div class="row"> (Application dropdown) </div>,
        //     <div class="row"> (Validation fields Tagify) </div>,
        //     <div class="dynamic-table" id="table-container-XXXX">…</div>
        //   ]
        //
        // We can identify each piece by label text, or by the presence of certain child elements, etc.

        // 1) Parse “Acquisition name” row
        const acqNameRow = blockEls.find((el) =>
            el.querySelector("label")?.textContent.includes("Acquisition name")
        );
        // The <input> that holds the (possibly updated) acquisition name:
        const acqInput = acqNameRow?.querySelector("input[type='text']");
        let userAcquisitionName = acqInput ? acqInput.value.trim() : "";
        if (!userAcquisitionName) {
            userAcquisitionName = "UntitledAcq";
        }

        // 3) Find the table container that holds the two tables (constant & variable)
        //    Usually the container has id like "table-container-<acquisition>"
        const tableContainer = blockEls.find((el) =>
            el.classList.contains("dynamic-table")
        );
        if (!tableContainer) {
            // If there's no table yet (maybe no fields selected?), store something minimal:
            acquisitionsObj[userAcquisitionName] = {
                fields: [],
                series: [],
            };
            return; // Move on to next acquisition
        }

        // We might have up to 2 tables in this container:
        const allTables = tableContainer.querySelectorAll("table");
        let constantTableEl = null;
        let variableTableEl = null;

        // Distinguish them by reading the first row's header cells
        allTables.forEach((table) => {
            const headers = table.querySelectorAll("tr:first-child th");
            const headerNames = Array.from(headers).map((h) => h.textContent.trim());
            if (headerNames.includes("Field") && headerNames.includes("Value")) {
                constantTableEl = table; // The constant fields table
            } else if (headerNames.includes("Series")) {
                variableTableEl = table; // The variable fields table
            }
        });

        // 4A) Parse constant fields (like your original code):
        const fieldsArray = [];
        if (constantTableEl) {
            const tableRows = Array.from(constantTableEl.querySelectorAll("tr")).slice(1); // skip header
            tableRows.forEach((tr) => {
                const tds = tr.querySelectorAll("td");
                if (tds.length < 2) return;
                const fieldName = tds[0].textContent.trim();
                const cellContainer = tds[1].querySelector("div");
                if (!cellContainer) return;

                const fieldObj = parseValidationCell(fieldName, cellContainer);
                if (fieldObj) fieldsArray.push(fieldObj);
            });
        }

        // 4B) Parse variable (series) table
        const seriesArray = [];
        if (variableTableEl) {
            // Grab header cells (should have "Series" plus the selected fields)
            const headerCells = variableTableEl.querySelectorAll("tr:first-child th");
            const colNames = Array.from(headerCells).map((h) => h.textContent.trim());

            // skip the header row
            const varRows = Array.from(variableTableEl.querySelectorAll("tr")).slice(1);
            varRows.forEach((tr) => {
                const dataCells = tr.querySelectorAll("td");
                if (!dataCells.length) return;

                // The first cell is the "Series" name
                const seriesCell = dataCells[0].querySelector("input");
                const seriesName = seriesCell ? seriesCell.value : "Series?";

                // The rest of the columns are fields
                const fieldsInSeries = [];
                for (let colIndex = 1; colIndex < dataCells.length; colIndex++) {
                    const colName = colNames[colIndex]; // e.g. "EchoTime", "RepetitionTime", ...
                    const cell = dataCells[colIndex];
                    const cellContainer = cell.querySelector("div");
                    if (!cellContainer) continue; // might be blank

                    const fieldObj = parseValidationCell(colName, cellContainer);
                    if (fieldObj) fieldsInSeries.push(fieldObj);
                }

                seriesArray.push({
                    name: seriesName,
                    fields: fieldsInSeries,
                });
            });
        }

        // 5) Combine everything into final structure for this acquisition
        acquisitionsObj[userAcquisitionName] = {
            fields: fieldsArray,
            series: seriesArray,
        };
    });

    // 6) Build final JSON and prompt user to download
    const template = { acquisitions: acquisitionsObj };
    downloadJSON(template, "dicom_template.json");
}

// Remainder: parseValidationCell & downloadJSON remain the same as in your code.
function parseValidationCell(fieldName, container) {
    const select = container.querySelector("select");
    if (!select) return null;

    const mode = select.value; // "value" | "range" | "tolerance" | "contains"

    const valueInput = container.querySelector(".valueInput input");
    const minInput = container.querySelector(".rangeInputs input:nth-child(1)");
    const maxInput = container.querySelector(".rangeInputs input:nth-child(2)");
    const containsIn = container.querySelector(".containsInput input");
    const valInput = container.querySelector(".valAndTolInput input:nth-child(1)");
    const tolInput = container.querySelector(".valAndTolInput input:nth-child(2)");

    let result = { field: fieldName };
    if (mode === "value") {
        const raw = valueInput?.value || "";
        result.value = parseStringValue(raw);
    } else if (mode === "range") {
        const rawMin = minInput?.value || "";
        const rawMax = maxInput?.value || "";
        result.min = parseStringValue(rawMin);
        result.max = parseStringValue(rawMax);
    } else if (mode === "contains") {
        const rawContains = containsIn?.value || "";
        result.contains = parseStringValue(rawContains);
    } else if (mode === "tolerance") {
        const rawVal = valInput?.value || "";
        const rawTol = tolInput?.value || "";
        result.value = parseStringValue(rawVal);
        result.tolerance = parseStringValue(rawTol);
    }

    return result;
}

function parseStringValue(raw) {
    if (!raw) return raw; // empty or undefined

    // If raw includes commas, split and parse each piece
    if (raw.includes(",")) {
        const parts = raw.split(",").map(s => s.trim());
        return parts.map(str => parseSingleValue(str));
    } else {
        return parseSingleValue(raw);
    }
}

// Helper: Checks if a string is purely numeric before converting
function parseSingleValue(str) {
    // Regex: optional sign (+/-), then digits, optional decimal + digits
    const numericRegex = /^[+-]?\d+(\.\d+)?$/;

    // If matches purely numeric pattern, parse as float; otherwise keep as string
    if (numericRegex.test(str)) {
        return parseFloat(str);
    } else {
        return str;
    }
}

function downloadJSON(jsonData, filename) {
    const dataStr = JSON.stringify(jsonData, null, 2);
    const blob = new Blob([dataStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();

    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}
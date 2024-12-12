let jsonData = { acquisitions: {} };
const btnGenJSON = document.getElementById("fmGenRef_btnGenJSON");
const btnDownloadJSON = document.getElementById("fmGenRef_btnDownloadJSON");

async function fmGenRef_ValidateForm() {
  let valid = true;

  // Check if DICOM files are selected
  if (!document.getElementById("fmGenRef_DICOMs").files.length) {
    valid = false;
  }

  // Validate acquisition fields using Tagify
  if (!tagInputfmGenRef_acquisitionFields || tagInputfmGenRef_acquisitionFields.getTagElms().length === 0) {
    valid = false;
  }

  // Validate reference fields using Tagify
  if (!tagInputfmGenRef_referenceFields || tagInputfmGenRef_referenceFields.getTagElms().length === 0) {
    valid = false;
  }

  // Enable or disable the Generate JSON button
  btnGenJSON.disabled = !valid;

  return valid;
}

async function fmGenRef_genRef() {
  btnGenJSON.disabled = true;

  if (!pyodide) {
    btnGenJSON.textContent = "Loading Pyodide...";
    pyodide = await initPyodide(); // Call the corrected initialization function
  }

  btnGenJSON.textContent = "Loading DICOMs...";
  const dicomFiles = await loadDICOMs("fmGenRef_DICOMs");
  const fmGenRef_acquisitionFields = tagInputfmGenRef_acquisitionFields.value.map(tag => tag.value);
  const fmGenRef_referenceFields = tagInputfmGenRef_referenceFields.value.map(tag => tag.value);

  pyodide.globals.set("dicom_files", dicomFiles);
  pyodide.globals.set("acquisition_fields", fmGenRef_acquisitionFields);
  pyodide.globals.set("reference_fields", fmGenRef_referenceFields);

  btnGenJSON.textContent = "Generating JSON...";
  const output = await pyodide.runPythonAsync(`
    import json
    from dicompare import load_dicom_session
    from dicompare.cli.gen_session import create_json_reference

    acquisition_fields = list(acquisition_fields)
    reference_fields = list(reference_fields)

    in_session = load_dicom_session(
      dicom_bytes=dicom_files,
      acquisition_fields=acquisition_fields,
    )

    # Filter fields in DataFrame
    relevant_fields = set(acquisition_fields + reference_fields)
    in_session = in_session[list(relevant_fields.intersection(in_session.columns)) + ["Acquisition"]]

    # Generate JSON reference
    json_reference = create_json_reference(
        session_df=in_session,
        acquisition_fields=acquisition_fields,
        reference_fields=reference_fields
    )

    # Return JSON reference
    json.dumps(json_reference, indent=4)
  `);

  btnGenJSON.textContent = "Parsing JSON...";
  jsonData = JSON.parse(output);
  fmGenRef_renderEditor(); // Render all acquisitions and their contents
  btnGenJSON.disabled = false;
  btnGenJSON.textContent = "Generate JSON Reference";
}

function fmGenRef_renderEditor() {
  const editor = document.getElementById("jsonEditor");
  editor.innerHTML = ""; // Clear the editor

  Object.entries(jsonData.acquisitions).forEach(([acqKey, acqData]) => {
      const acqDiv = document.createElement("div");
      acqDiv.className = "acquisition-container";

      acqDiv.innerHTML = `
          <div class="row grid">
              <label>Acquisition:</label>
              <input type="text" value="${acqKey}" onchange="updateAcquisitionName('${acqKey}', this.value)">
              <button class="delete" onclick="deleteAcquisition('${acqKey}')">🗑</button>
          </div>
      `;

      const fieldsContainer = document.createElement("div");
      fieldsContainer.className = "fields-container";

      fieldsContainer.innerHTML = `
          <div class="field-row header">
              <span></span>
              <span>Field</span>
              <span></span>
              <span>Value/Contains</span>
              <span></span>
              <span>Mode</span>
              <span></span>
              <span>Tolerance</span>
              <span></span>
          </div>
      `;

      acqData.fields.forEach((field, index) => {
          const fieldValue = Array.isArray(field.value) ? JSON.stringify(field.value) : field.value || "";
          const mode = field.contains ? "Contains" : "Value";
          const tolerance = field.tolerance || "";

          fieldsContainer.innerHTML += `
              <div class="field-row">
                  <label></label>
                  <input type="text" class="tagify" value="${field.field}" onchange="updateAcquisitionFieldName('${acqKey}', ${index}, this.value)">
                  <label></label>
                  <input type="text" value='${fieldValue}' onchange="updateAcquisitionFieldValue('${acqKey}', ${index}, this.value)">
                  <label></label>
                  <select onchange="updateAcquisitionFieldMode('${acqKey}', ${index}, this.value)">
                      <option value="Value" ${mode === "Value" ? "selected" : ""}>Value</option>
                      <option value="Contains" ${mode === "Contains" ? "selected" : ""}>Contains</option>
                  </select>
                  <label></label>
                  <input type="number" step="0.01" value="${tolerance}" placeholder="Tolerance (optional)" onchange="updateAcquisitionFieldTolerance('${acqKey}', ${index}, this.value)">
                  <button class="delete" onclick="deleteAcquisitionField('${acqKey}', ${index})">🗑</button>
              </div>
          `;
      });

      fieldsContainer.innerHTML += `<button class="add" onclick="addAcquisitionField('${acqKey}')">Add Field</button>`;
      acqDiv.appendChild(fieldsContainer);

      // Add series sections
      const seriesContainer = document.createElement("div");
      const seriesData = acqData.series || [];
      seriesData.forEach((series, seriesIndex) => {
          const seriesDiv = document.createElement("div");
          seriesDiv.className = "series-container";

          seriesDiv.innerHTML = `
              <div class="row grid">
                  <label>Series:</label>
                  <input type="text" value="${series.name}" onchange="updateSeriesName('${acqKey}', ${seriesIndex}, this.value)">
                  <button class="delete" onclick="deleteSeries('${acqKey}', ${seriesIndex})">🗑</button>
              </div>
          `;

          const seriesFieldsContainer = document.createElement("div");
          seriesFieldsContainer.className = "fields-container";

          seriesFieldsContainer.innerHTML = `
              <div class="field-row header">
                  <span></span>
                  <span>Field</span>
                  <span></span>
                  <span>Value/Contains</span>
                  <span></span>
                  <span>Mode</span>
                  <span></span>
                  <span>Tolerance</span>
                  <span></span>
              </div>
          `;

          series.fields.forEach((field, fieldIndex) => {
              const fieldValue = Array.isArray(field.value) ? JSON.stringify(field.value) : field.value || "";
              const mode = field.contains ? "Contains" : "Value";
              const tolerance = field.tolerance || "";

              seriesFieldsContainer.innerHTML += `
                  <div class="field-row">
                      <label></label>
                      <input type="text" class="tagify" value="${field.field}" onchange="updateSeriesFieldName('${acqKey}', ${seriesIndex}, ${fieldIndex}, this.value)">
                      <label></label>
                      <input type="text" value='${fieldValue}' onchange="updateSeriesFieldValue('${acqKey}', ${seriesIndex}, ${fieldIndex}, this.value)">
                      <label></label>
                      <select onchange="updateSeriesFieldMode('${acqKey}', ${seriesIndex}, ${fieldIndex}, this.value)">
                          <option value="Value" ${mode === "Value" ? "selected" : ""}>Value</option>
                          <option value="Contains" ${mode === "Contains" ? "selected" : ""}>Contains</option>
                      </select>
                      <label></label>
                      <input type="number" step="0.01" value="${tolerance}" placeholder="Tolerance (optional)" onchange="updateSeriesFieldTolerance('${acqKey}', ${seriesIndex}, ${fieldIndex}, this.value)">
                      <button class="delete" onclick="deleteSeriesField('${acqKey}', ${seriesIndex}, ${fieldIndex})">🗑</button>
                  </div>
              `;
          });

          seriesFieldsContainer.innerHTML += `<button class="add" onclick="addSeriesField('${acqKey}', ${seriesIndex})">Add Field</button>`;
          seriesDiv.appendChild(seriesFieldsContainer);

          seriesContainer.appendChild(seriesDiv);
      });

      seriesContainer.innerHTML += `<button class="add" onclick="addSeries('${acqKey}')">Add Series</button>`;
      acqDiv.appendChild(seriesContainer);

      editor.appendChild(acqDiv);
  });

  const actionsContainer = document.createElement("div");
  actionsContainer.className = "actions";

  const addAcquisitionButton = document.createElement("button");
  addAcquisitionButton.id = "fmGenRef_btnAddAcquisition";
  addAcquisitionButton.className = "add";
  addAcquisitionButton.textContent = "Add Acquisition";
  addAcquisitionButton.onclick = () => {
      const newAcqName = `Acquisition${Object.keys(jsonData.acquisitions).length + 1}`;
      jsonData.acquisitions[newAcqName] = { fields: [], series: [] };
      fmGenRef_renderEditor();
  };

  const downloadJsonButton = document.createElement("button");
  downloadJsonButton.id = "fmGenRef_btnDownloadJSON";
  downloadJsonButton.className = "green";
  downloadJsonButton.textContent = "Download JSON";
  downloadJsonButton.onclick = fmGenRef_downloadJson;

  actionsContainer.appendChild(addAcquisitionButton);
  actionsContainer.appendChild(downloadJsonButton);

  editor.appendChild(actionsContainer);
}

function updateAcquisitionFieldMode(acqName, fieldIndex, mode) {
  const field = jsonData.acquisitions[acqName].fields[fieldIndex];
  if (mode === "Contains") {
      delete field.value;
      field.contains = field.contains || "";
  } else {
      delete field.contains;
      field.value = field.value || "";
  }
}

function updateAcquisitionFieldTolerance(acqName, fieldIndex, tolerance) {
  const field = jsonData.acquisitions[acqName].fields[fieldIndex];
  if (tolerance) {
      field.tolerance = parseFloat(tolerance);
  } else {
      delete field.tolerance;
  }
}

function updateSeriesFieldMode(acqName, seriesIndex, fieldIndex, mode) {
  const field = jsonData.acquisitions[acqName].series[seriesIndex].fields[fieldIndex];
  if (mode === "Contains") {
      delete field.value;
      field.contains = field.contains || "";
  } else {
      delete field.contains;
      field.value = field.value || "";
  }
}

function updateSeriesFieldTolerance(acqName, seriesIndex, fieldIndex, tolerance) {
  const field = jsonData.acquisitions[acqName].series[seriesIndex].fields[fieldIndex];
  if (tolerance) {
      field.tolerance = parseFloat(tolerance);
  } else {
      delete field.tolerance;
  }
}

function updateAcquisitionFieldName(acqName, fieldIndex, newName) {
  jsonData.acquisitions[acqName].fields[fieldIndex].field = newName;
}

function updateAcquisitionFieldValue(acqName, fieldIndex, newValue) {
  jsonData.acquisitions[acqName].fields[fieldIndex].value = newValue;
}

function updateSeriesFieldName(acqName, seriesIndex, fieldIndex, newName) {
  jsonData.acquisitions[acqName].series[seriesIndex].fields[fieldIndex].field = newName;
}

function updateSeriesFieldValue(acqName, seriesIndex, fieldIndex, newValue) {
  jsonData.acquisitions[acqName].series[seriesIndex].fields[fieldIndex].value = newValue;
}

function deleteAcquisition(acqName) {
  delete jsonData.acquisitions[acqName];
  fmGenRef_renderEditor();
}

function deleteAcquisitionField(acqName, fieldIndex) {
  jsonData.acquisitions[acqName].fields.splice(fieldIndex, 1);
  fmGenRef_renderEditor();
}

function addAcquisitionField(acqName) {
  jsonData.acquisitions[acqName].fields.push({ field: "", value: "" });
  fmGenRef_renderEditor();
}

function deleteSeries(acqName, seriesIndex) {
  jsonData.acquisitions[acqName].series.splice(seriesIndex, 1);
  fmGenRef_renderEditor();
}

function addSeries(acqName) {
  jsonData.acquisitions[acqName].series.push({ name: "", fields: [] });
  fmGenRef_renderEditor();
}

function deleteSeriesField(acqName, seriesIndex, fieldIndex) {
  jsonData.acquisitions[acqName].series[seriesIndex].fields.splice(fieldIndex, 1);
  fmGenRef_renderEditor();
}

function addSeriesField(acqName, seriesIndex) {
  jsonData.acquisitions[acqName].series[seriesIndex].fields.push({ field: "", value: "" });
  fmGenRef_renderEditor();
}

function updateAcquisitionName(oldName, newName) {
  if (newName && !jsonData.acquisitions[newName]) {
    jsonData.acquisitions[newName] = jsonData.acquisitions[oldName];
    delete jsonData.acquisitions[oldName];
    fmGenRef_renderEditor();
  }
}

function updateSeriesName(acqName, seriesIndex, newName) {
  jsonData.acquisitions[acqName].series[seriesIndex].name = newName;
}

function fmGenRef_downloadJson() {
  const blob = new Blob([JSON.stringify(jsonData, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "edited_json.json";
  a.click();
}

document.getElementById("fmGenRef_DICOMs").addEventListener("change", () => {
  fmGenRef_ValidateForm();
});

// check if form is ready whene the DICOM selector, Acquisition Fields, or Reference Fields change
document.getElementById("fmGenRef_acquisitionFields").addEventListener("change", () => {
  setTimeout(() => {
    fmGenRef_ValidateForm();
  }, 300);
});

// check if form is ready whene the DICOM selector, Acquisition Fields, or Reference Fields change
document.getElementById("fmGenRef_referenceFields").addEventListener("change", () => {
  setTimeout(() => {
    fmGenRef_ValidateForm();
  }, 300);
});

// validate on form load
fmGenRef_ValidateForm();
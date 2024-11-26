let jsonData = { acquisitions: {} };
const btnGenJSON = document.getElementById("fmGenRef_btnGenJSON");
const btnDownloadJSON = document.getElementById("fmGenRef_btnDownloadJSON");

async function fmGenRef_ValidateForm() {
  valid = true;
  if (!document.getElementById("fmGenRef_DICOMs").files.length) {
    valid = false;
  }

  // acquisitionFieldInput is a tagify object, so check getTagElms
  if (tagInputfmGenRef_acquisitionFields.getTagElms().length === 0) {
    valid = false;
  }

  if (tagInputfmGenRef_referenceFields.getTagElms().length === 0) {
    valid = false;
  }

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
    from dcm_check import generate_json_ref

    output = generate_json_ref(
      acquisition_fields=acquisition_fields,
      reference_fields=reference_fields,
      name_template="{ProtocolName}-{SeriesDescription}",
      dicom_files=dicom_files
    )
    json.dumps(output, indent=4)
  `);

  btnGenJSON.textContent = "Parse JSON...";
  jsonData = JSON.parse(output);
  fmGenRef_renderEditor(); // Render all acquisitions and their contents
  btnDownloadJSON.disabled = false; // Enable the Download JSON button
  btnGenJSON.disabled = false;
  btnGenJSON.textContent = "Generate JSON Reference";
}

function fmGenRef_renderEditor() {
  const editor = document.getElementById("jsonEditor");
  editor.innerHTML = ""; // Clear the editor

  Object.entries(jsonData.acquisitions).forEach(([acqKey, acqData]) => {
    const acqDiv = document.createElement("div");
    acqDiv.className = "acquisition-container";

    const readableName = acqKey.split('-')[0]; // Extract a human-readable name

    // Acquisition Name and Delete Button
    acqDiv.innerHTML = `
      <div class="row grid">
        <label>Acquisition:</label>
        <input type="text" value="${readableName}" onchange="updateAcquisitionName('${acqKey}', this.value)">
        <button class="delete" onclick="deleteAcquisition('${acqKey}')">🗑</button>
      </div>
    `;


    // Acquisition Fields with Headers
    const fieldsContainer = document.createElement("div");
    fieldsContainer.className = "fields-container";

    fieldsContainer.innerHTML = `
      <div class="field-row header">
        <span></span>
        <span>Field</span>
        <span></span>
        <span>Value</span>
        <span></span>
      </div>
    `;

    acqData.fields.forEach((field, index) => {
      const fieldValue = Array.isArray(field.value) ? JSON.stringify(field.value) : field.value;

      fieldsContainer.innerHTML += `
        <div class="field-row">
          <label></label>
          <input type="text" class="tagify" value="${field.field}" onchange="updateAcquisitionFieldName('${acqKey}', ${index}, this.value)">
          <label></label>
          <input type="text" value='${fieldValue}' onchange="updateAcquisitionFieldValue('${acqKey}', ${index}, this.value)">
          <button class="delete" onclick="deleteAcquisitionField('${acqKey}', ${index})">🗑</button>
        </div>
      `;
    });

    fieldsContainer.innerHTML += `<button class="add" onclick="addAcquisitionField('${acqKey}')">Add Field</button>`;
    acqDiv.appendChild(fieldsContainer);

    // Series Section
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
          <span>Value</span>
          <span></span>
        </div>
      `;

      series.fields.forEach((field, fieldIndex) => {
        const fieldValue = Array.isArray(field.value) ? JSON.stringify(field.value) : field.value;

        seriesFieldsContainer.innerHTML += `
          <div class="field-row">
            <label></label>
            <input type="text" class="tagify" value="${field.field}" onchange="updateSeriesFieldName('${acqKey}', ${seriesIndex}, ${fieldIndex}, this.value)">
            <label></label>
            <input type="text" value='${fieldValue}' onchange="updateSeriesFieldValue('${acqKey}', ${seriesIndex}, ${fieldIndex}, this.value)">
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

document.getElementById("fmGenRef_btnAddAcquisition").addEventListener("click", () => {
  // Generate a unique acquisition name
  const newAcqName = `Acquisition${Object.keys(jsonData.acquisitions).length + 1}`;
  jsonData.acquisitions[newAcqName] = { fields: [], series: [] };
  fmGenRef_renderEditor(); // Re-render the editor
});

// disable Generate JSON Reference button if no DICOM files are selected
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
